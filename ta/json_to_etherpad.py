#!/usr/bin/env python2
# -*- coding: utf8 -*-
#
# Copyright (c) 2015 unfoldingWord
# http://creativecommons.org/licenses/MIT/
# See LICENSE file for details.
#
#  Contributors:
#  Phil Hopper <phillip_hopper@wycliffeassociates.org>
#

import argparse
import cgi
import codecs
import shlex
from subprocess import Popen, PIPE

# noinspection PyUnresolvedReferences
from datetime import datetime
from etherpad_lite import EtherpadLiteClient, EtherpadException
import json
import os
import re
import sys
import yaml

# YAML file heading data format:
#
# ---
# title: Test tA Module 1
# question: What is Module 1 all about?
# manual: Section_Name(?)
# volume: 1
# slug: testmod1 - unique in all tA
# dependencies: ["intro", "howdy"] - slugs
# status: finished
# ---
#
# Derived URL = en/ta/vol1/section_name/testmod1

NEW_LANGUAGE_CODE = ''
CONTINUE_ON_ERROR = 0
DELETE_EXISTING = -1
ERROR_COUNT = 0

YAML_REGEX = re.compile(r"(---\s*\n)(.+?)(^-{3}\s*\n)+?(.*)$", re.DOTALL | re.MULTILINE)


class SelfClosingEtherpad(EtherpadLiteClient):
    """
    This class is here to enable with...as functionality for the EtherpadLiteClient
    """

    def __init__(self):
        super(SelfClosingEtherpad, self).__init__()

        # noinspection PyBroadException
        try:
            # ep_api_key.door43 indicates this is a remote connection
            if os.path.exists('/usr/share/httpd/.ssh/ep_api_key.door43'):
                key_file = '/usr/share/httpd/.ssh/ep_api_key.door43'
                base_url = 'https://pad.door43.org/api'

            else:
                key_file = '/usr/share/httpd/.ssh/ep_api_key'
                base_url = 'http://localhost:9001/api'

            pw = open(key_file, 'r').read().strip()
            self.base_params = {'apikey': pw}
            self.base_url = base_url

        except:
            e1 = sys.exc_info()[0]
            print 'Problem logging into Etherpad via API: {0}'.format(e1)
            sys.exit(1)

    def __enter__(self):
        return self

    # noinspection PyUnusedLocal
    def __exit__(self, exception_type, exception_val, trace):
        return


class SectionData(object):
    def __init__(self, name, page_list=None):
        if not page_list:
            page_list = []
        self.name = self.get_name(name)
        self.page_list = page_list

    @staticmethod
    def get_name(name):
        if name.lower().startswith('intro'):
            return 'Introduction'

        if name.lower().startswith('transla'):
            return 'Translation'

        if name.lower().startswith('check'):
            return 'Checking'

        if name.lower().startswith('tech'):
            return 'Technology'

        if name.lower().startswith('proc'):
            return 'Process'

        return name


class PageData(object):
    def __init__(self, section_name, page_id, yaml_data, page_text):
        self.section_name = section_name
        self.page_id = page_id
        self.yaml_data = yaml_data
        self.page_text = page_text


def log_this(string_to_log, top_level=False):
    if string_to_log == '':
        return

    print string_to_log
    if top_level:
        msg = u'\n=== {0} ==='.format(string_to_log)
    else:
        msg = u'\n  * {0}'.format(string_to_log)

    with codecs.open(LOGFILE, 'a', 'utf-8') as file_out:
        file_out.write(msg)


def log_error(string_to_log):
    global ERROR_COUNT
    global CONTINUE_ON_ERROR

    ERROR_COUNT += 1
    log_this(string_to_log)

    # prompt user to continue or exit
    if CONTINUE_ON_ERROR == 1:
        return

    user_input = raw_input('Continue after error (y|N|a): ')

    if user_input == 'y':
        return

    if user_input == 'a':
        CONTINUE_ON_ERROR = 1
        return

    # if we get here we should exit
    sys.exit(1)


def parse_ta_modules(raw_text):
    """
    Returns a dictionary containing the URLs in each major section
    :param raw_text: str
    :rtype: SectionData[]
    """

    returnval = []

    # remove everything before the first ======
    pos = raw_text.find("\n======")
    tmpstr = raw_text[pos + 7:]

    # break at "\n======" for major sections
    arr = tmpstr.split("\n======")
    for itm in arr:

        # split section at line breaks
        lines = filter(None, itm.splitlines())

        # section name is the first item
        section_name = lines[0].replace('=', '').strip()

        # remove section name from the list
        del lines[0]
        urls = []

        # process remaining lines
        for i in range(0, len(lines)):

            # find the URL, just the first one
            match = re.search(r"(https://[\w\./-]+)", lines[i])
            if match:
                pos = match.group(1).rfind("/")
                if pos > -1:
                    urls.append(match.group(1)[pos + 1:])
                else:
                    urls.append(match.group(1))

        # remove duplicates
        no_dupes = set(urls)

        # add the list of URLs to the dictionary
        returnval.append(SectionData(section_name, no_dupes))

    return returnval


def get_ta_pages(e_pad, sections):
    """

    :param e_pad: SelfClosingEtherpad
    :param sections: SectionData[]
    :return: PageData[]
    """

    pages = []

    for section in sections:
        section_key = section.name

        for pad_id in section.page_list:

            log_this('Retrieving page: ' + section_key.lower() + ':' + pad_id, True)

            # get the page
            try:
                page_raw = e_pad.getText(padID=pad_id)
                match = YAML_REGEX.match(page_raw['text'])
                if match:

                    # check for valid yaml data
                    yaml_data = get_page_yaml_data(match.group(2))
                    if yaml_data is None:
                        continue

                    if yaml_data == {}:
                        log_error('No yaml data found for ' + pad_id)
                        continue

                    pages.append(PageData(section_key, pad_id, yaml_data, match.group(4)))

                else:
                    log_error('Yaml header not found ' + pad_id)

            except EtherpadException as e:

                # ignore missing pads
                if e.message == u'padID does not exist':
                    continue

                log_error(e.message)

            except Exception as ex:
                log_error(str(ex))

    return pages


def get_page_yaml_data(raw_yaml_text, skip_checks=False):

    returnval = {}

    # convert windows line endings
    cleaned = raw_yaml_text.replace("\r\n", "\n")

    # replace curly quotes
    cleaned = cleaned.replace(u'“', '"').replace(u'”', '"')

    # split into individual values, removing empty lines
    parts = filter(bool, cleaned.split("\n"))

    # check each value
    for part in parts:

        # split into name and value
        pieces = part.split(':', 1)

        # must be 2 pieces
        if len(pieces) != 2:
            log_error('Bad yaml format => ' + part)
            return None

        # try to parse
        # noinspection PyBroadException
        try:
            parsed = yaml.load(part)

        except:
            log_error('Not able to parse yaml value => ' + part)
            return None

        if not isinstance(parsed, dict):
            log_error('Yaml parse did not return the expected type => ' + part)
            return None

        # add the successfully parsed value to the dictionary
        for key in parsed.keys():
            returnval[key] = parsed[key]

    if not skip_checks and not check_yaml_values(returnval):
        returnval['invalid'] = True

    return returnval


def check_yaml_values(yaml_data):

    return_val = True

    # check the required yaml values
    if not check_value_is_valid_int('volume', yaml_data):
        log_error('Volume value is not valid.')
        return_val = False

    if not check_value_is_valid_string('manual', yaml_data):
        log_error('Manual value is not valid.')
        return_val = False

    if not check_value_is_valid_string('slug', yaml_data):
        log_error('Volume value is not valid.')
        return_val = False
    else:
        # slug cannot contain a dash, only underscores
        test_slug = str(yaml_data['slug']).strip()
        if '-' in test_slug:
            log_error('Slug values cannot contain hyphen (dash).')
            return_val = False

    if not check_value_is_valid_string('title', yaml_data):
        return_val = False

    return return_val


def check_value_is_valid_string(value_to_check, yaml_data):

    if value_to_check not in yaml_data:
        log_error('"' + value_to_check + '" data value for page is missing')
        return False

    if not yaml_data[value_to_check]:
        log_error('"' + value_to_check + '" data value for page is blank')
        return False

    data_value = yaml_data[value_to_check]

    if not isinstance(data_value, str) and not isinstance(data_value, unicode):
        log_error('"' + value_to_check + '" data value for page is not a string')
        return False

    if not data_value.strip():
        log_error('"' + value_to_check + '" data value for page is blank')
        return False

    return True


# noinspection PyBroadException
def check_value_is_valid_int(value_to_check, yaml_data):

    if value_to_check not in yaml_data:
        log_error('"' + value_to_check + '" data value for page is missing')
        return False

    if not yaml_data[value_to_check]:
        log_error('"' + value_to_check + '" data value for page is blank')
        return False

    data_value = yaml_data[value_to_check]

    if not isinstance(data_value, int):
        try:
            data_value = int(data_value)
        except:
            try:
                data_value = int(float(data_value))
            except:
                return False

    return isinstance(data_value, int)


def get_existing_page_by_slug(ep_pages, slug):
    """
    :param ep_pages: PageData[]
    :param slug: string
    :return: PageData|None
    """

    for ep_page in ep_pages:

        # for type hinting
        assert isinstance(ep_page, PageData)

        if ep_page.yaml_data['slug'] == slug:
            return ep_page

    # return None if not found
    log_error('Page "' + slug + '" not found in etherpad.')
    return None


def update_ep_page(e_pad, ep_page, json_page):
    """

    :param e_pad: SelfClosingEtherpad
    :param ep_page: PageData
    :param json_page:
    :return:
    """
    global NEW_LANGUAGE_CODE

    log_this('Updating ' + ep_page.page_id)

    if 'question' in json_page and json_page['question']:
        ep_page.yaml_data['question'] = json_page['question']

    if 'title' in json_page and json_page['title']:
        ep_page.yaml_data['title'] = json_page['title']

    html = u''
    for body_item in json_page['body']:
        html += process_item(body_item)

    # update internal links to other tA pages in this namespace
    html = html.replace(u'&#x2F;p&#x2F;ta-', u'&#x2F;p&#x2F;' + NEW_LANGUAGE_CODE + u'-ta-')
    html = html.replace(u'[[en:ta:', u'[[' + NEW_LANGUAGE_CODE + u':ta:')
    html = html.replace(u'[[:en:ta:', u'[[:' + NEW_LANGUAGE_CODE + u':ta:')
    html = html.replace(u'>en:ta:', u'>' + NEW_LANGUAGE_CODE + u':ta:')
    html = html.replace(u'[[en:ta|', u'[[' + NEW_LANGUAGE_CODE + u':ta|')
    html = html.replace(u'[[:en:ta|', u'[[:' + NEW_LANGUAGE_CODE + u':ta|')
    html = html.replace(u'<br><strong>namespace:</strong> en<br>', u'<br><strong>namespace:</strong> ' +
                        NEW_LANGUAGE_CODE + u'<br>')

    # convert html to dokuwiki format
    dokuwiki = html_to_dokuwiki(html)

    # start with the YAML header
    html = u'<!DOCTYPE HTML><html><body>---&nbsp;<br>'

    # add the YAML header
    for key, value in ep_page.yaml_data.iteritems():
        html += u'<strong>' + key + u':</strong> '

        if type(value) in [str, unicode]:
            html += value
        elif type(value) in [int, long, float]:
            html += str(value)
        elif type(value) is list:
            html += u'['
            comma = u''
            for item in value:
                html += comma + u'"' + item + u'"'
                comma = u','
            html += u']'

        html += u'<br>'

    html += u'---&nbsp;<br><br>'

    # escape special characters the dokuwiki text
    dokuwiki = cgi.escape(dokuwiki)

    # append the dokuwiki text
    html += dokuwiki + u'<br></body></html>'

    # html encode the text
    html = html.replace(u'\n', u'<br>')
    html = html.encode('ascii', 'xmlcharrefreplace')

    # make sure we have a good pad id
    pad_id = check_pad_id(e_pad, ep_page.page_id)

    # update the text now
    e_pad.setHTML(padID=pad_id, html=html)


def check_pad_id(e_pad, current_id):
    global NEW_LANGUAGE_CODE

    # make sure the page_id begins with the language code
    pad_id = current_id
    if not pad_id.startswith(NEW_LANGUAGE_CODE + u'-'):
        pad_id = NEW_LANGUAGE_CODE + u'-' + pad_id
        pad_exists = False

        # check if the new pad already exists
        # noinspection PyBroadException
        try:
            e_pad.getText(padID=pad_id)

            # if you are here is exists
            pad_exists = True

        except:
            pass

        if not pad_exists:
            e_pad.createPad(padID=pad_id)

    return pad_id


def process_item(item):

    html = u'<' + item['tag'] + u'>'

    if 'items' in item:
        html += u'\n'
        for sub_item in item['items']:
            html += process_item(sub_item)

    else:
        html += item['text']

    html += u'</' + item['tag'] + u'>\n'
    return html


def html_to_dokuwiki(html):
    command = shlex.split(u'pandoc -f html -t dokuwiki')
    com = Popen(command, shell=False, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    out, ret = com.communicate(html.encode('utf8'))
    return out.decode('utf-8').strip()


if __name__ == '__main__':

    # process input args
    parser = argparse.ArgumentParser(description='Imports a JSON file into existing Etherpad pages')
    parser.add_argument('-l', '--lang', help='Language Code')
    parser.add_argument('-f', '--file', help='JSON file to import', default=0, type=int)
    args = parser.parse_args()

    # prompt user for language code if not supplied on the command line
    if not args.lang:
        lang_code = raw_input('Enter the target language code: ')
        if lang_code:
            args.lang = lang_code

    # if no language code supplied, exit
    if not args.lang:
        print 'Exiting because no language code was supplied.'
        sys.exit(1)

    # prompt user for JSON file if not supplied on the command line
    if not args.file:
        json_file = raw_input('Enter the JSON file name: ')
        if json_file:
            args.file = json_file

    # if no JSON file supplied, exit
    if not args.file:
        print 'Exiting because no JSON file was supplied.'
        sys.exit(1)

    NEW_LANGUAGE_CODE = args.lang
    LOGFILE = '/var/www/vhosts/door43.org/httpdocs/data/gitrepo/pages/playground/' +\
              NEW_LANGUAGE_CODE + 'ta_json_to_etherpad.log.txt'

    # enable logging for this script
    log_dir = os.path.dirname(LOGFILE)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, 0755)

    if os.path.exists(LOGFILE):
        os.remove(LOGFILE)

    log_this('Most recent run: ' + datetime.utcnow().strftime('%Y-%m-%d %H:%M') + ' UTC', True)
    log_this('Loading JSON file: ' + args.file, True)

    # use encoding 'utf-8-sig' to correctly decode files with BOM
    with codecs.open(args.file, 'r', 'utf-8-sig') as in_file:
        imported_pages = json.load(in_file)

    log_this('Opening Etherpad', True)
    ta_pages = None

    # get the existing pages
    with SelfClosingEtherpad() as ep:
        text = ep.getText(padID=NEW_LANGUAGE_CODE + '-ta-modules')
        ta_sections = parse_ta_modules(text['text'])
        ta_pages = get_ta_pages(ep, ta_sections)

        # update the pages with the new translations
        for manual in imported_pages['manuals']:
            for page in manual['pages']:

                # find the corresponding etherpad page
                pad_page = get_existing_page_by_slug(ta_pages, page['slug'])
                if pad_page:
                    update_ep_page(ep, pad_page, page)

    # remember last_checked for the next time
    if ERROR_COUNT > 0:
        if ERROR_COUNT == 1:
            log_this('1 error has been logged', True)
        else:
            log_this(str(ERROR_COUNT) + ' errors have been logged', True)

    log_this('Finished copying', True)
