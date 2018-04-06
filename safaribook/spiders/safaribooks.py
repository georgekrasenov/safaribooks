import os
import re
import ast
import shutil
from functools import partial
import codecs
import sys
reload(sys)
sys.setdefaultencoding('utf8')

import contextlib
import scrapy
import selenium.webdriver as webdriver
import selenium.webdriver.support.ui as ui
from scrapy.http import HtmlResponse
from scrapy.shell import inspect_response
from jinja2 import Template
import scrapy.spiders
from bs4 import BeautifulSoup

null = None
false = False
true = True

PAGE_TEMPLATE="""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title></title>
<link rel="stylesheet" type="text/css" href="css/ibisbook.css" />
{{cssfiles}}
</head>
{{body}}
</html>"""

class SafariBooksSpider(scrapy.spiders.Spider):
  toc_url = 'https://www.safaribooksonline.com/nest/epub/toc/?book_id='
  name = "SafariBooks"
  #allowed_domains = []
  start_urls = ["https://www.safaribooksonline.com/"]
  host = "https://www.safaribooksonline.com/"

  custom_settings = { 'REDIRECT_MAX_TIMES': 333, 'DUPEFILTER_DEBUG': True }

  def __init__(self, user='', password='', token='', bookid=''):
    self.user = user
    self.password = password
    self.bookid = bookid
    self.token = token
    self.book_name = ''
    self.cookies = None
    self.info = {}
    self._stage_toc = False
    self.initialize_output()
    self.css_paths = []

  def initialize_output(self):
    shutil.rmtree('output/', ignore_errors=True)
    shutil.copytree('data/', 'output/')

  def parse(self, response):
    return scrapy.FormRequest.from_response(
      response,
      formdata={"email": self.user, "password1": self.password},
      callback=self.saml_login)

  def saml_login(self, response):
    yield scrapy.FormRequest.from_response(
      response,
      formdata={"username": self.user, "password": self.password},
      callback=self.bunit_login, dont_filter=True)

  def bunit_login(self, response):
    yield scrapy.FormRequest.from_response(
      response,
      formdata={"token": self.token},
      callback=self.saml_resume_login)

  def saml_resume_login(self, response):
    yield scrapy.FormRequest.from_response(
      response,
      formdata={},
      callback=self.after_login)

  def after_login(self, response):
    # Loose role to decide if user signed in successfully.
    if '/login' in response.url:
      self.logger.error("Failed login")
      return
    yield scrapy.Request(self.toc_url+self.bookid, callback=self.parse_toc)

  def parse_cover_img(self, name, response):
    #inspect_response(response, self)
    with open("./output/OEBPS/cover-image.jpg", "w") as f:
      f.write(response.body)

  def parse_content_img(self, img, response):
    img_path = os.path.join("./output/OEBPS", img)

    img_dir = os.path.dirname(img_path)
    if not os.path.exists(img_dir):
      os.makedirs(img_dir)

    with open(img_path, "wb") as f:
      f.write(response.body)

  def parse_css_file(self, cssUrl, response):
    css_path = os.path.join("./output/OEBPS/css/" + os.path.basename(cssUrl))

    css_dir = os.path.dirname(css_path)
    if not os.path.exists(css_dir):
      os.makedirs(css_dir)

    with codecs.open(css_path, "wb", "utf-8") as f:
      f.write(response.body)

  def parse_page_json(self, title, bookid, response):
    page_json = eval(response.body)
    yield scrapy.Request(page_json["content"], callback=partial(self.parse_page, title, bookid, page_json["full_path"]))

  def parse_page(self, title, bookid, path, response):
    template = Template(PAGE_TEMPLATE)

    # path might have nested directory
    dirs_to_make = os.path.join('./output/OEBPS', os.path.dirname(path))
    if not os.path.exists(dirs_to_make):
      os.makedirs(dirs_to_make)

    # Build head css section
    cssfiles = ""
    # for css_path in self.css_paths:
    #   cssfiles += '<link rel="stylesheet" type="text/css" href="css/' + css_path + '" />\n'

    with codecs.open("./output/OEBPS/" + path, "wb", "utf-8") as f:
      # pretty_head = BeautifulSoup(response.body).find('head').prettify()
      pretty_body = BeautifulSoup(response.body).find('body')
      f.write(template.render(cssfiles=cssfiles, body=pretty_body))

    for img in response.xpath("//img/@src").extract():
      if img:
        img = img.replace('../','') # fix for books which are one level down
        yield scrapy.Request(self.host + '/library/view/' + title + '/' + bookid + '/' + img,
                             callback=partial(self.parse_content_img, img))

  def save_css(self, response):
    soup = BeautifulSoup(response.body)

    for cssStyle in soup.findAll(attrs={"title" : "ibis-book"}):
      path = "./output/OEBPS/css/ibisbook.css"
      dirs = os.path.dirname(path)
      if not os.path.exists(dirs):
        os.makedirs(dirs)

      with codecs.open(path, "a", "utf-8") as f:
        f.write(cssStyle.contents[0])

    # for cssUrl in [link["href"] for link in soup.findAll("link") if "stylesheet" in link.get("rel", [])]:
    #   if cssUrl:
    #     # Build URL for CSS files
    #     if cssUrl.startswith("//"):
    #       cssUrl = "https:" + cssUrl
    #     elif cssUrl.startswith("/"):
    #       cssUrl = self.host + cssUrl[1:]

    #     self.css_paths.append(os.path.basename(cssUrl))

    #     # Make Requests
    #     yield scrapy.Request(cssUrl,
    #                          callback=partial(self.parse_css_file, cssUrl))

  def parse_toc(self, response):
    try:
      toc = eval(response.body)
    except:
      self.logger.error("Failed evaluating toc body: %s" % response.body)
      return

    self._stage_toc = True

    self.book_name = toc['title_safe']
    self.book_title = re.sub(r'["%*/:<>?\\|~\s]', r'_', toc['title']) # to be used for filename
    cover_path, = re.match(r'<img src="(.*?)" alt.+', toc["thumbnail_tag"]).groups()
    yield scrapy.Request(self.host + cover_path,
                         callback=partial(self.parse_cover_img, "cover-image"))
    for item in toc["items"]:
      yield scrapy.Request(self.host + item["url"], callback=partial(self.parse_page_json, toc["title_safe"], toc["book_id"]))

    # Get CSS files
    yield scrapy.Request(self.host + toc['detail_url'] + toc["items"][0]["full_path"], callback=self.save_css)

    template = Template(file("./output/OEBPS/content.opf").read())
    with codecs.open("./output/OEBPS/content.opf", "wb", "utf-8") as f:
      f.write(template.render(info=toc))

    template = Template(file("./output/OEBPS/toc.ncx").read())
    with codecs.open("./output/OEBPS/toc.ncx", "wb", "utf-8") as f:
      f.write(template.render(info=toc))


  def closed(self, reason):
    if self._stage_toc == False:
      self.logger.info("Did not even got toc, ignore generated file operation.")
      return

    shutil.make_archive(self.book_name, 'zip', './output/')
    shutil.copy(self.book_name + '.zip', self.book_title + '-' + self.bookid + '.epub')
