#!/bin/bash

if ! [[ $4 =~ [0-9]+ ]]; then
    echo "Please give a pure digit book id, $4 is not an acceptable book id."
    exit -1
fi

scrapy crawl SafariBooks -a user=$1 -a password=$2 -a token=$3 -a bookid=$4
kindlegen *.epub
