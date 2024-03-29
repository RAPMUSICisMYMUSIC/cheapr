__author__ = 'vantani'
import bs4
import requests
import tld
import errno
import itertools
import os
import re
import urlparse
from flask import Flask
from collections import defaultdict
from database import (db)
from mobiles.models import MobileBrand
from mobiles.models import MobileModel
import urllib

import logging
#logging.basicConfig(filename="./cache/error.log")

"""
https://raw.githubusercontent.com/shurane/phonemakers/master/scraper.py

This grabs the phone data from GSMArena. It goes through a list of makers,
then goes through the list of phones by each maker, and then pulls out
whatever specs GSMArena lists for said phones.

The goal of this project is to make more informed data about which phones to
buy. You can filter by what operating system it has, when it was released,
whether it supports and SD card, the diagonal size of the screen, and more.
This relies entirely on the data from GSMArena and similar websites

Now we have all the details on a per-phone basis. Wonderful.

Some of my least finest work, but it serves the purpose.

TODO:
YhG1s and cdunklau from #python suggest me using Scrapy instead of
BeautifulSoup + requests
"""

# http://stackoverflow.com/a/600612/198348
def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc: # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else: raise

URL = "http://www.gsmarena.com/makers.php3"
TLD_URL = tld.get_tld(URL)
USER_AGENT = "Mozilla/5.0 (X11; Linux i686) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/29.0.1547.49 Safari/537.36"

HEADERS = { "User-Agent" : USER_AGENT
           , "Accept" : "text/html" }
CACHE = "./cache"
STATIC = "../static/"
# I wonder if there's a more clever way than using 'directory'
CACHE_MAKERS = "{0}/makers".format(CACHE)
CACHE_PHONES = "{0}/phones".format(CACHE)
CACHE_IMAGES = "{0}cache/images".format(STATIC)
mkdir_p(CACHE)
mkdir_p(CACHE_MAKERS)
mkdir_p(CACHE_PHONES)
mkdir_p(CACHE_IMAGES)

def rget(url, directory=CACHE, **kwargs):
    # if cached, open cached file instead of using requests
    urlpath = urlparse.urlparse(url).path.strip("/")
    urlpath = os.path.join(directory, urlpath)
    try:
        return open(urlpath).read()
    except IOError as e:
        if e.errno != errno.ENOENT:
            raise

        r = requests.get(url,headers=HEADERS,**kwargs)
        with open(urlpath,"w") as f:
            # I'm confused! YEAARGH isn't utf-8 automatic in requests?
            # http://stackoverflow.com/a/9942822/198348
            f.write(r.text.encode("utf-8").strip())
        return r.text

def rget_imgs(url, directory=CACHE_IMAGES, **kwargs):
    # if cached, open cached file instead of using requests
    filename = urlparse.urlparse(url).path.split("/")[3]
    urlpath = os.path.join(directory, filename)
    print urlpath
    #Check if file is present
    if os.path.isfile(urlpath):
        return "/static/cache/images/"+filename
    else:
        urllib.urlretrieve(url, urlpath)
        return "/static/cache/images/"+filename


def cleanse(string):
    string = re.sub("\xa0","",string)
    string = re.sub("\r\n","\n",string)
    string = string.strip()
    return string

class Maker(object):
    def __init__(self,name,url,img):
        self.name = name
        self.url = url
        self.img = img
        self.results = []
    def __str__(self):
        return "<Maker({0},{1})>".format(self.name,self.url)
    def __repr__(self):
        return str(self)

    def get_phones(self):
        rtext = rget(self.url, directory=CACHE_MAKERS)
        soup = bs4.BeautifulSoup(rtext)
        phone_soups = soup.select("#main .makers > ul > li > a")
        phones = []
        for phone_soup in phone_soups:
            name = phone_soup.strong.text
            href = "http://{0}/{1}".format(TLD_URL,phone_soup.attrs["href"])
            phones.append(Phone(name=name,url=href,maker=self.name))

        self.phones = phones

        return phones

class Phone(object):
    def __init__(self,name="",url="",maker="",img=""):
        self.name = name
        self.url = url
        self.maker = maker
        self.fields = {}
        self.description = ""
        self.img = img
        self.canonical_name = "{0} {1}".format(self.maker,self.name)
    def __str__(self):
        return "<Phone({0},{1},{2},{3})>".format(self.maker,self.name,self.url,self.img)
    def __repr__(self):
        return str(self)

    def get_fields(self):
        rtext = rget(self.url,directory=CACHE_PHONES)
        soup = bs4.BeautifulSoup(rtext)
        description = soup.select("#specs-list > p")
        self.description = description[0].text if description else None
        img_src = soup.select("#specs-cp-pic > a > img")
        self.img = rget_imgs(img_src[0].get('src')) if img_src else None
        fields = {}
        sections_with_emptykey = defaultdict(int)

        tables = soup.select("table")
        for table in tables:
            title = table.th.text
            subvalues = itertools.izip(table.select(".ttl"),
                                       table.select(".nfo"))
            subdict = {}
            for key, value in subvalues:
                clean_key = cleanse(key.text)
                clean_value = cleanse(value.text)
                subdict[clean_key] = clean_value

                if not clean_key:
                    sections_with_emptykey[title] += 1

            fields[title] = subdict

        if sections_with_emptykey:
            logging.warn("{0}: Sections with empty keys\n{1}"
                         .format(self,sections_with_emptykey))
        self.fields = fields

        return fields

def get_makers(url):
    rtext = rget(url)
    root_soup = bs4.BeautifulSoup(rtext)
    makers = root_soup.select("#main tr > td > a")
    results = []
    # every other element is a duplicate
    for maker in makers[::2]:
        href = "http://{0}/{1}".format(TLD_URL,maker.attrs["href"])
        name = maker.img.attrs["alt"]
        img = rget_imgs(maker.img.attrs["src"])

        m = Maker(name,href,img)
        results.append(m)

    return results


if __name__ == "__main__":

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://cheapr:cheapr@localhost/cheapr'
    db.app=app
    db.init_app(app)

    with app.app_context():
        # Extensions like Flask-SQLAlchemy now know what the "current" app
        # is while within this block. Therefore, you can now run........
        db.create_all()


    makers = get_makers(URL)
    mdict = {}

    print("#Brands")
    id=1
    maker_models=[]
    for maker in makers:
        print("Working on " + maker.name)
        maker_model = MobileBrand(id=id, name=maker.name, img=maker.img, link=maker.url,top_brand=0)
        maker_models.append(maker_model)
        id=id+1
        mdict[maker.name] = maker.get_phones()

    db.session.add_all(maker_models)
    db.session.commit()

    print("#Phones")
    phone_models=[]
    phones = list(itertools.chain(*mdict.values()))
    for index, phone in enumerate(phones):
        if index % 100 == 0:
            print("{:4} Working on {} {}".format(index, phone.maker, phone.name))
        try:
            phone.get_fields()
            phone_model = MobileModel(id=index, name=phone.name, canonical_name=phone.canonical_name, url=phone.url,
                                      img=phone.img, fields=phone.fields, description=phone.description,
                                      maker=phone.maker,top_mobile=0)
            phone_models.append(phone_model)
        except Exception as e:
            logging.error("encountered exception for {0}".format(phone.name))
            logging.exception(e)

    db.session.add_all(phone_models)
    db.session.commit()

    if True:
        import jsonpickle
        with open(os.path.join(CACHE,"mdict.json"),"w") as fm:
            mdict_json = jsonpickle.encode(mdict)
            fm.write(mdict_json)


