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
#

import codecs
import json
import os
import re
import shlex
from datetime import datetime, time
import sys
from lxml import etree
from subprocess import Popen, PIPE
import yaml
from etherpad_lite import EtherpadLiteClient, EtherpadException


# YAML file heading data format:
#
# ---
# title: Test tA Module 1
# question: What is Module 1 all about?
# manual: Section_Name
# volume: 1
# slug: testmod1 - unique in all tA
# dependencies: ["intro", "howdy"] - a single slug or an array of slugs
# status: finished
# credits: Used with permission from someone
# ---
#

LOGFILE = '/var/www/vhosts/door43.org/httpdocs/data/gitrepo/pages/playground/ta_json.log.txt'
JSONFILE = '/var/www/vhosts/api.unfoldingword.org/httpdocs/ta_vol1_en_markdown.json'

H1REGEX = re.compile(r"(.*?)((?:<p>)?======\s*)(.*?)(\s*======(?:</p>)?)(.*?)", re.DOTALL | re.MULTILINE)
H2REGEX = re.compile(r"(.*?)((?:<p>)?=====\s*)(.*?)(\s*=====(?:</p>)?)(.*?)", re.DOTALL | re.MULTILINE)
H3REGEX = re.compile(r"(.*?)((?:<p>)?====\s*)(.*?)(\s*====(?:</p>)?)(.*?)", re.DOTALL | re.MULTILINE)
H4REGEX = re.compile(r"(.*?)((?:<p>)?===\s*)(.*?)(\s*===(?:</p>)?)(.*?)", re.DOTALL | re.MULTILINE)
H5REGEX = re.compile(r"(.*?)((?:<p>)?==\s*)(.*?)(\s*==(?:</p>)?)(.*?)", re.DOTALL | re.MULTILINE)
LINKREGEX = re.compile(r"(.*?)(\[{2}?)(.*?)(\]{2}?)(.*?)", re.DOTALL | re.MULTILINE)
ITALICREGEX = re.compile(r"(.*?)(?<!:)(//)(.*?)(?<!http:|ttps:)(//)(.*?)", re.DOTALL | re.MULTILINE)
BOLDREGEX = re.compile(r"(.*?)(\*\*)(.*?)(\*\*)(.*?)", re.DOTALL | re.MULTILINE)
NLNLREGEX = re.compile(r"(.*?)(\\\\\s*\n\\\\\s*\n)(.*?)", re.DOTALL | re.MULTILINE)
NLREGEX = re.compile(r"(.*?)(\\\\\s*\n)(.*?)", re.DOTALL | re.MULTILINE)
ULREGEX = re.compile(r"(.*?)(?<!\n)(\n\s\s\*)(.+)(?!\n\s\s\*)(.*?)", re.DOTALL | re.MULTILINE)
UL2REGEX = re.compile(r"(.*?)(\n\s\s\*)(.+\n)(?!\s\s)(.*?)", re.DOTALL | re.MULTILINE)
PNGREGEX = re.compile(r"(.*?)(\{\{)(.*?)(\.png)(.*?)(\}\})(.*?)", re.DOTALL | re.MULTILINE)

error_count = 0

# enable logging for this script
log_dir = os.path.dirname(LOGFILE)
if not os.path.exists(log_dir):
    os.makedirs(log_dir, 0755)

if os.path.exists(LOGFILE):
    os.remove(LOGFILE)


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
        self.pages = []


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


def log_this(string_to_log, top_level=False):
    print string_to_log
    if top_level:
        msg = u'\n=== {0} ==='.format(string_to_log)
    else:
        msg = u'\n  * {0}'.format(string_to_log)

    with codecs.open(LOGFILE, 'a', 'utf-8') as file_out:
        file_out.write(msg)


def log_error(string_to_log):

    global error_count
    error_count += 1
    log_this(u'<font inherit/inherit;;#bb0000;;inherit>{0}</font>'.format(string_to_log))


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
    :return: SectionData[]
    """

    regex = re.compile(r"(---\s*\n)(.+)(^-{3}\s*\n)+?(.*)$", re.DOTALL | re.MULTILINE)

    for section in sections:
        section_key = section.name

        for pad_id in section.page_list:

            log_this('Retrieving page: ' + section_key.lower() + ':' + pad_id, True)

            # get the page
            try:
                page_raw = e_pad.getText(padID=pad_id)
                match = regex.match(page_raw['text'])
                if match:

                    yaml_data = get_page_yaml_data(match.group(2))
                    if yaml_data is None:
                        continue

                    if yaml_data == {}:
                        log_error('No yaml data found for ' + pad_id)
                        continue

                    if yaml_data['volume'] != 1:
                        continue

                    if match.group(4).strip(" \t\n\r") == '':
                        continue

                    html = markdown_to_html(match.group(4))
                    dom = etree.HTML(html)
                    items = []

                    for element in dom[0]:

                        # if this is a list we need to list the items separately
                        if element.tag == 'ul' or element.tag == 'ol':
                            li_list = []
                            for li in element:
                                li_list.append({'tag': 'li', 'text': u''.join(li.itertext())})

                            items.append({'tag': element.tag, 'items': li_list})

                        else:
                            items.append({'tag': element.tag, 'text': u''.join(element.itertext())})

                    section.pages.append([yaml_data, items])
                else:
                    log_error('Yaml header not found ' + pad_id)

            except EtherpadException as e:
                log_error(e.message)

            except Exception as ex:
                log_error(str(ex))

    return sections


def get_page_yaml_data(raw_yaml_text):

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

    if not check_yaml_values(returnval):
        returnval['invalid'] = True

    return returnval


def check_yaml_values(yaml_data):

    returnval = True

    # check the required yaml values
    if not check_value_is_valid_int('volume', yaml_data):
        log_error('Volume value is not valid.')
        returnval = False

    if not check_value_is_valid_string('manual', yaml_data):
        log_error('Manual value is not valid.')
        returnval = False

    if not check_value_is_valid_string('slug', yaml_data):
        log_error('Volume value is not valid.')
        returnval = False
    else:
        # slug cannot contain a dash, only underscores
        test_slug = str(yaml_data['slug']).strip()
        if '-' in test_slug:
            log_error('Slug values cannot contain hyphen (dash).')
            returnval = False

    if not check_value_is_valid_string('title', yaml_data):
        returnval = False

    return returnval


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


def create_json(sections):

    json_obj = {'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M') + ' UTC', 'manuals': []}

    for section in sections:
        manual = {'name': section.name, 'pages': []}

        for page in section.pages:
            json_page = {}

            yaml_data = page[0]
            yaml_keys = sorted(yaml_data)

            for yaml_key in yaml_keys:
                json_page[yaml_key] = yaml_data[yaml_key]

            json_page['body'] = page[1]

            manual['pages'].append(json_page)

        json_obj['manuals'].append(manual)

    with codecs.open(JSONFILE, 'w', 'utf-8') as out_file:
        json.dump(json_obj, out_file)


def markdown_to_html(dokuwiki):

    markdown = dokuwiki_to_markdown(dokuwiki)
    markdown = NLNLREGEX.sub(r'\1\n\n\3', markdown)
    markdown = NLREGEX.sub(r'\1\n\n\3', markdown)
    markdown = ULREGEX.sub(r'\1\n\2\3\4', markdown)
    markdown = UL2REGEX.sub(r'\1\2\3\n\4', markdown)

    command = shlex.split('/usr/bin/pandoc -f markdown_phpextra -t html')
    com = Popen(command, shell=False, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    out, err = com.communicate(markdown.encode('utf-8'))
    html = out.decode('utf-8')

    # fix some things pandoc doesn't convert
    html = re.sub(LINKREGEX, convert_link, html)
    html = ITALICREGEX.sub(r'\1<em>\3</em>\5', html)
    html = BOLDREGEX.sub(r'\1<strong>\3</strong>\5', html)

    return html


def dokuwiki_to_markdown(dokuwiki):

    markdown = H1REGEX.sub(r'\1# \3 #\5', dokuwiki)
    markdown = H2REGEX.sub(r'\1## \3 ##\5', markdown)
    markdown = H3REGEX.sub(r'\1### \3 ###\5', markdown)
    markdown = H4REGEX.sub(r'\1#### \3 ####\5', markdown)
    markdown = H5REGEX.sub(r'\1##### \3 #####\5', markdown)

    # {{:en:ta:tech:translating_in_ts_-_obs_v2.mp4|Resources Video}}
    # {{:en:ta:ol2sl2sl2tl_small_600-174.png?nolink&600x174}}
    markdown = re.sub(PNGREGEX, convert_png_link, markdown)

    return markdown


def convert_link(match):
    try:
        parts = match.group(3).split('|')
        if isinstance(parts, list):
            if len(parts) > 1:
                return match.group(1) + '<a href="' + dokuwiki_to_html_link(parts[0]) + '">' + parts[1] + '</a>' + \
                    match.group(5)
            else:
                return match.group(1) + '<a href="' + dokuwiki_to_html_link(parts[0]) + '">' + parts[0] + '</a>' + \
                    match.group(5)
        else:
            return match.group(1) + '<a href="' + dokuwiki_to_html_link(parts) + '">' + parts + '</a>' + match.group(5)

    except Exception as ex:
        log_error(str(ex))


def dokuwiki_to_html_link(dokuwiki_link):

    # if this is already a valid URL, return it unchanged
    if dokuwiki_link[:4].lower() == 'http':
        return dokuwiki_link

    # if this is a dokuwiki link, convert it
    if ':' in dokuwiki_link:
        if dokuwiki_link[:1] == ':':
            dokuwiki_link = dokuwiki_link[1:]

        return 'https://door43.org/' + dokuwiki_link.replace(':', '/')

    return dokuwiki_link


def convert_png_link(match):
    # "![{$frame['id']}]({$image_file})\\"
    try:
        parts = match.group(3).split('|')
        if isinstance(parts, list):
            return match.group(1) + '![Image](https://door43.org/_media' + parts[0].replace(':', '/') + '.png)' + \
                match.group(7)
        else:
            return match.group(1) + '![Image](https://door43.org/_media' + parts.replace(':', '/') + '.png)' + \
                match.group(7)

    except Exception as ex:
        log_error(str(ex))


if __name__ == '__main__':

    log_this('Most recent run: ' + datetime.utcnow().strftime('%Y-%m-%d %H:%M') + ' UTC', True)
    log_this('Checking for changes in Etherpad', True)

    # get the last run time
    last_checked = 0
    last_file = '.lastEpToDwRun'
    if os.path.isfile(last_file):
        with open(last_file, 'r') as f:
            last_checked = int(float(f.read()))

    ta_pages = None

    with SelfClosingEtherpad() as ep:
        text = ep.getText(padID='ta-modules')
        ta_sections = parse_ta_modules(text['text'])
        ta_sections = get_ta_pages(ep, ta_sections)

    create_json(ta_sections)

    # remember last_checked for the next time
    if error_count == 0:
        with open(last_file, 'w') as f:
            f.write(str(time.time()))
    else:
        if error_count == 1:
            log_this('1 error has been logged', True)
        else:
            log_this(str(error_count) + ' errors have been logged', True)

    log_this('Finished updating', True)
