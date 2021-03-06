#encoding=utf-8

import django
django.setup()

import requests
import re
import os
from sources.functions import getGematria
from sefaria.model import *
from sefaria.system.exceptions import InputError
from collections import OrderedDict
from bs4 import BeautifulSoup, element
from time import sleep
import shutil
from segments import *
from sources.functions import *
import unicodedata
from sefaria.utils.hebrew import strip_cantillation
from research.mesorat_hashas_sefaria.mesorat_hashas import ParallelMatcher
from data_utilities.util import WeightedLevenshtein
import datetime
import traceback

class Sheet(object):

    def __init__(self, html, parasha, title, year, ref, sefer, perek_info):
        self.html = html
        self.title = title
        self.parasha = parasha
        self.en_parasha = Term().load({"titles.text": parasha}).name if " - " not in parasha else parasha
        self.sefer, self.perakim, self.pasukim = self.extract_perek_info(perek_info)
        self.en_sefer = library.get_index(sefer).title
        self.he_year = re.sub(u"שנת", u"", year).strip()
        self.year = getGematria(self.he_year) + 5000  # +1240, jewish year is more accurate
        self.en_year = getGematria(self.he_year) + 1240
        #self.pasukim = self.get_ref(ref)  # (re.sub(u"(פרק(ים)?|פסוק(ים)?)", u"", ref).strip())
        self.sheet_remark = u""
        self.header_links = None  # this will link to other  nechama sheets (if referred).
        self.quotations = []  # last one in this list is the current ref
        self.current_section = 0
        self.div_sections = [] # BeautifulSoup objects that will eventually become converted into Section objects stored in self.sections
        self.sections = []
        self.sources = []


    def create_sheetsources_from_objsource(self):
        # first source in the sheet is the sheet remark
        if self.sheet_remark:
            self.sources.append({"outsideText": self.sheet_remark,
             "options": {
                 "indented": "indented-1",
                 "sourceLayout": "",
                 "sourceLanguage": "hebrew",
                 "sourceLangLayout": ""
             }
             })
        for isection, section in enumerate(self.sections):
            for isegment, segment in enumerate(section.segment_objects):
                if isinstance(segment, Source):
                    parser.try_parallel_matcher(segment)
                seg_sheet_source = segment.create_source()
                self.sources.extend(seg_sheet_source if isinstance(seg_sheet_source, list) else [seg_sheet_source]) # todo: problem with nested it doesn't it doesn't go through the PM...


    def prepare_sheet(self, add_to_title=""):
       sheet_json = {}
       sheet_json["status"] = "public" #"private" #
       sheet_json["group"] ="Nechama Leibowitz' Source Sheets"#"Nechama Leibowitz' Source Sheets"
       sheet_json["title"] = u'{} - {} {}'.format(self.title, re.search('(\d+)\.', self.html).group(1), add_to_title)
       sheet_json["summary"] = u"{} ({})".format(self.en_year, self.year)
       sheet_json["sources"] = self.sources
       sheet_json["options"] = {"numbered": 0, "assignable": 0, "layout": "sideBySide", "boxed": 0, "language": "hebrew", "divineNames": "noSub", "collaboration": "none", "highlightMode": 0, "bsd": 0, "langLayout": "heRight"}
       sheet_json["tags"] = [unicode(self.en_year), unicode(self.en_parasha)]
       post_sheet(sheet_json, server=parser.server)



    def extract_perek_info(self, perek_info):
        def get_pasukim_for_perek(sefer, perek):
            en_sefer = library.get_index(sefer).title
            return str(len(Ref(u"{} {}".format(en_sefer, perek)).all_segment_refs()))

        #three formats: Perek 2; Perek 2, Pasuk 3-9; Perek 2, 4 - Perek 3, 2 (last one may lose pasuk info as well
        print perek_info
        sefer = perek_info.split()[0]
        try:
            en_sefer = library.get_index(sefer).title
        except BookNameError:
            sefer = " ".join(perek_info.split()[0:2]) # For Melachim Bet
            en_sefer = library.get_index(sefer).title
        perek_info = perek_info.replace(u"פרקים", u"Perek").replace(u"פרק", u"Perek").replace(u"פסוקים", u"Pasuk").replace(u"פסוק", u"Pasuk").strip()
        perek_info = perek_info.replace(sefer, u"")
        if len(perek_info.split("Perek")) - 1 == 2: #we know it's the third case
            pereks = [perek_info.split(" - ")[0], perek_info.split(" - ")[1]]
            pasuks = [-1, -1]
            for p, perek in enumerate(pereks):
                if ", " in perek:
                    pereks[p] = str(getGematria(perek.replace("Perek ", "").split(", ")[0]))
                    pasuks[p] = pereks[p] + ":" + str(getGematria(perek.replace("Perek ", "").split(", ")[1]))
                else:
                    pereks[p] = str(getGematria(pereks[p].replace("Perek ", "")))
            if pasuks[0] == -1:
                pasuks[0] = pereks[0] + ":1"
            if pasuks[1] == -1:
                pasuks[1] = pereks[1] + ":" + get_pasukim_for_perek(sefer, pereks[1])
            pasuks = Ref("{} {}-{}".format(en_sefer, pasuks[0], pasuks[1]))
        elif "Pasuk" in perek_info: #we know it's the second case
            pereks = re.findall(u"Perek\s+(.{1,3})\s?", perek_info)
            assert len(pereks) is 1
            pereks = [str(getGematria(pereks[0]))]
            pasuks = re.findall(u"Pasuk\s+(.{1,18})\s?", perek_info)[0].split(" - ")
            for p, pasuk in enumerate(pasuks):
                pasuks[p] = getGematria(pasuk)
            if len(pasuks) is 2:
                pasuks = range(pasuks[0], pasuks[1]+1)
                pasuks = Ref(en_sefer+" "+pereks[0]+":"+str(pasuks[0])+"-"+str(pasuks[-1]))
            else:
                assert len(pasuks) is 1
                pasuks = Ref(en_sefer + " " + pereks[0] + ":" + str(pasuks[0]))
        else: #first case
            pereks = re.findall(u"Perek\s+(.{1,3})\s?", perek_info)
            assert len(pereks) is 1
            pereks = [str(getGematria(pereks[0]))]
            pasuks = []
            last_pasuk = get_pasukim_for_perek(sefer, pereks[0])
            pasuks = Ref(en_sefer+" "+pereks[0]+":1-"+last_pasuk)

        return (sefer, pereks, pasuks)

    def get_ref(self, he_ref):
        # he_ref = re.sub(u"(פרק(ים)?|פסוק(ים)?)", u"", he_ref).strip()
        # split = re.split()
        try:
            r = Ref(he_ref)
            print r.normal()
        except InputError:
            print 'InputError'
            return None
        return r

    def parse_as_text(self):
        """
        this method loops over the bs tag obj of the sections and creates Section() objs from them
        and then loops over Section objs crerated to init the list of Segment() objs
        :return:
        """

        # intro_segment = intro_tuple = None

        # init
        for div in self.div_sections:
            self.current_section += 1
            new_section = Section(self.current_section, self.perakim, self.pasukim, soupObj=div)
            assert str(self.current_section) in div['id']
            self.sections.append(new_section)
            # if div.text.replace(" ", "") == "":
            #     continue

            # # removes nodes with no content
            # soup_segments = new_section.get_children_with_content(div)
            #
            # # blockquote is really just its children so get replace it with them
            # # and tables  need to be handled recursively
            # soup_segments = new_section.check_for_blockquote_and_table(soup_segments, level=2)
            #
            # #create Segment objects out of the BeautifulSoup objects
            # new_section.classify_segments(soup_segments)
            # new_section.title = re.sub(u"<.*?>", u"", new_section.segment_objects[0].text)
            # new_section.letter = re.search(u"(.{1,2})\.\s", new_section.title).group(1)
            # self.sections.append(new_section)
            # print u"appended {}".format(new_section.title)

        # init Segment() obj from bs_objs in each section
        for section in self.sections:
            section.add_segments(section.soupObj)
            print u"appended {}".format(section.title)


class Section(object):

    def __init__(self, number, perakim, pasukim, soupObj):
        self.soupObj = soupObj
        self.number = number  # which number section am I
        self.possible_perakim = perakim  # list of perakim: the assumption is that any perek referenced will be in this list
        self.possible_pasukim = pasukim  # Ref range: the assumption is that any pasuk referenced will be inside the range
        self.letter = ""
        self.title = ""
        self.segment_objects = []  # list of Segment objs
        self.RT_Rashi = False
        self.current_parsha_ref = ""
        self.current_perek = self.possible_perakim[0]
        self.current_pasuk = self.possible_pasukim.sections[-1] #the lowest pasuk in the range
        self.has_nested = []

    @staticmethod
    def get_Tags(segment):

        if isinstance(segment,element.Tag):
            return [t for t in segment.contents if isinstance(t, element.Tag)]
        elif isinstance(segment,list):
            return [t for t in segment if isinstance(t, element.Tag)]
        else:
            return None

    def add_segments(self, div):

        # removes nodes with no content
        soup_segments = self.get_children_with_content(div)
        # blockquote is really just its children so get replace it with them
        # and tables  need to be handled recursively
        soup_segments = self.check_for_blockquote_and_table(soup_segments)

        # create Segment objects out of the BeautifulSoup objects
        self.classify_segments(soup_segments) #self.segment_objects += self.classify_segments(soup_segments)
        header = filter(lambda x: isinstance(x, Header), self.segment_objects)[0]
        self.title = header.header_text
        self.letter = header.letter
        return

    def classify_segments(self, soup_segments):
        """
        Classifies each segments based on its role such as "question", "header", or quote from "bible"
        and then sets each segment to be a tuple that tells us in order:
        who says it, what do they say, where does it link to
        If Nechama makes a comment:
        ("Nechama", text, "")
        If Rashi:
        ("Rashi", text, ref_to_rashi)
        :param soup_segments:
        :return:
        """
        segment_objects = []
        current_source = None
        nested_candidates = {} # OrderedDict() # this is a Dict of nested obj, and the q will be do we wan't them as nested or as originals.

        if parser.old:
            for i, segment in enumerate(soup_segments):
                relevant_text = self.format(self.relevant_text(segment))  # if it's Tag, tag.text; if it's NavigableString, just the string
                if Header.is_header(segment):
                    segment_objects.append(Header(segment)) #self.segment_objects.append(Header(segment))
                # if i == 0 and not self.segment_objects: #there isn't a header yet. should not use place in the list... :(
                #     self.segment_objects.append(Header(segment))
                #     # assert Header.is_header(segment), "Header should be first."
                #     continue
                elif Question.is_question(segment):
                    nested_seg = Question.nested(segment)
                    if nested_seg:
                        self.has_nested += [i]
                        nested_candidates[i] = Nested([Question(segment), self.classify_segments(Section.get_Tags(nested_seg))], self.segment_objects)
                        segment_objects.append(nested_candidates[i]) #the idea here is that we have a hybrid Question/other smaller obj, and we will need to chose whitch is better fit for this segment in this Section
                        # self.add_segments(nested_seg)
                    else:  # not nested q so should append this q, otherwise it is a nested q. so it shouldn't be appended cause the children will be appended
                        segment_objects.append(Question(segment)) #self.segment_objects.append(Question(segment))
                elif Table.is_table(segment):  # these tables we want as they are so just str(segment)
                    segment_objects.append(Table(segment)) #self.segment_objects.append(Table(segment))
                elif Source.is_source_text(segment, parser.important_classes):
                    # this is a comment by a commentary, bible, or midrash
                    segment_class = segment.attrs["class"][0]  # is it source, bible, or midrash?
                    assert len(segment.attrs["class"]) == 1, "More than one class"
                    if not current_source:
                        current_source = [x for x in segment_objects if isinstance(x, Source)][-1] #[x for x in self.segment_objects if isinstance(x, Source)][-1]
                    current_source = current_source.add_text(segment, segment_class) #returns current_source if there's no text, OR returns a new Source object if current_source already has text
                                                                                    #the latter case occurs when for example it says "Rashi" followed by multiple comments
                    segment_objects.append(current_source) #self.segment_objects.append(current_source)
                    if not current_source.ref:
                        continue
                    if current_source.index_not_found():
                        if current_source.about_source_ref not in parser.index_not_found.keys():
                            parser.index_not_found[current_source.about_source_ref] = []
                        parser.index_not_found[current_source.about_source_ref].append((self.current_parsha_ref, current_source.about_source_ref))
                    continue
                elif Nechama_Comment.is_comment(soup_segments, i, parser.important_classes):  # above criteria not met, just an ordinary comment
                    segment_objects.append(Nechama_Comment(relevant_text)) # self.segment_objects.append(Nechama_Comment(relevant_text))
                else:  # must be a Source Ref, so parse it
                    next_segment_class = (soup_segments[i + 1].attrs["class"][0], None if "id" not in soup_segments[i + 1].attrs.keys() else soup_segments[i + 1].attrs["id"]) # get the class of this ref and it's comment
                    current_source = self.parse_ref(segment, relevant_text, next_segment_class)
        else:
            soup_segments = [sp_segment for sp_segment in soup_segments if not isinstance(sp_segment, element.NavigableString)
                                                                            or not len(sp_segment.replace("\r\n", "")) < 3]
            for i, segment in enumerate(soup_segments):
                sheet_segment = self.classify(segment, i, soup_segments)
                if sheet_segment:
                    self.segment_objects.append(sheet_segment)
        return  # self.segment_objects
            #     if current_source.index_not_found():
            #         parser.index_not_found[parser.current_file_path].append(current_source.about_source_ref)
            #     continue
            # elif Nechama_Comment.is_comment(soup_segments, i, parser.important_classes):  # above criteria not met, just an ordinary comment
            #     self.segment_objects.append(Nechama_Comment(relevant_text))
            # else:  # must be a Source Ref, so parse it
            #     next_segment_class = (soup_segments[i + 1].attrs["class"][0], None if "id" not in soup_segments[i + 1].attrs.keys() else soup_segments[i + 1].attrs["id"]) # get the class of this ref and it's comment
            #     current_source = self.parse_ref(segment, relevant_text, next_segment_class)


    def classify(self, sp_segment, i, soup_segments):
        """

        :param sp_segment: beuitiful soup <tag> to classify into our obj and Nested
        :return: our obj (or Nested)
        """

        relevant_text = self.format(self.relevant_text(sp_segment))  # if it's Tag, tag.text; if it's NavigableString, just the string
        if Header.is_header(sp_segment):
            return Header(sp_segment)  # self.segment_objects.append(Header(segment))
        elif Question.is_question(sp_segment):
            nested_seg = Question.nested(sp_segment)
            if nested_seg:
                return Nested(Question(sp_segment))
            else:
                return Question(sp_segment)
        elif Table.is_table(sp_segment):  # these tables we want as they are so just str(segment)
            return Table(sp_segment)
        elif Source.is_source_text(sp_segment, parser.important_classes):
        # this is a comment by a commentary, bible, or midrash that should be added as text to a Source created previously already.
            segment_class = sp_segment.attrs["class"][0]  # is it source, bible, or midrash?

            current_source = [x for x in self.segment_objects if (isinstance(x, Source) and x.current)][-1]
            current_source.add_text(sp_segment, segment_class)
            # return current_source
    #     elif Source.is_source_text(sp_segment, parser.important_classes):
    #         # what is in this segment we need to learn it and parse it. is this the element of the ref or the source or the comment after?
    #         # and whitch parts of it do we want to be in the source obj?
    #         return Source(r)
        elif Nechama_Comment.is_comment(soup_segments, i, parser.important_classes):  # above criteria not met, just an ordinary comment
            return Nechama_Comment(relevant_text)  # self.segment_objects.append(Nechama_Comment(relevant_text))
        else:  # must be a Source Ref, so parse it
            next_segment_class = (soup_segments[i + 1].attrs["class"][0],
                                  None if "id" not in soup_segments[i + 1].attrs.keys() else soup_segments[i + 1].attrs[
                                      "id"])  # get the class of this ref and it's comment
            # next_segment_class = ["parshan"]
            current_source = self.parse_ref(sp_segment, relevant_text, next_segment_class)
            current_source.current = True
            return current_source

    def look_at_next_segment(self):
        pass

    def get_term(self, poss_title):
        # return the english index name corresponding to poss_title or None
        poss_title = poss_title.strip().replace(":", "")

        # already found it
        if poss_title in parser._term_cache:
            return parser._term_cache[poss_title]
        # this title is unusual so look in term_mapping for it
        if poss_title in parser.term_mapping:
            parser._term_cache[poss_title] = parser.term_mapping[poss_title]
            return parser._term_cache[poss_title]
        if [re.search(title, poss_title) for title in parser.has_parasha] != [None]:
            poss_title = self.ignore_parasha_name(poss_title)
        term = Term().load({"titles.text": poss_title})
        if poss_title in library.full_title_list('he'):
            parser._term_cache[poss_title] = library.get_index(poss_title).title
            return parser._term_cache[poss_title]
        elif term:
            term_name = term.name
            likely_index_title = u"{} on {}".format(term_name, parser.en_sefer)
            if likely_index_title in library.full_title_list('en'):
                parser._term_cache[poss_title] = likely_index_title
                return parser._term_cache[poss_title]
        parser._term_cache[poss_title] = None
        return None

    def ignore_parasha_name(self, string):
        parasha_found = [x in string for x in library.get_term_dict('he').keys()]
        if parasha_found:
            return re.sub(parasha_found[0], u"", string)
        return string

    def get_a_tag_from_ref(self, segment, relevant_text):
        starts_perek_or_pasuk = lambda x: (x.startswith(u"פרק ") or x.startswith(u"פסוק ") or
                                x.startswith(u"פרקים ") or x.startswith(u"פסוקים "))

        if segment.name == "a":
            a_tag = segment
        else:
            a_tag = segment.find('a')

        real_title = ""

        # if a_tag and segment.find("u") and a_tag.text != segment.find("u").text: #case where
        a_tag_is_entire_comment = False
        if a_tag:
            a_tag_is_entire_comment = len(a_tag.text.split()) == len(segment.text.split())
            real_title = self.get_term(a_tag.text)
        elif relevant_text in parser.term_mapping:
            real_title = parser.term_mapping[relevant_text]
        if not real_title and (self.RT_Rashi and starts_perek_or_pasuk(segment.text)):  # every ref starting with Perek or Pasuk in RT_Rashi is really to Rashi
            real_title = "Rashi on {}".format(parser.en_sefer)
        return (real_title, a_tag, a_tag_is_entire_comment)

    def parse_ref(self, segment, relevant_text, next_segment_info):
        next_segment_class = next_segment_info[0]

        # check if it's in Perek X, Pasuk Y format
        is_tanakh = (relevant_text.startswith(u"פרק ") or relevant_text.startswith(u"פסוק ") or
                     relevant_text.startswith(u"פרקים ") or relevant_text.startswith(u"פסוקים "))

        real_title, found_a_tag, a_tag_is_entire_comment = self.get_a_tag_from_ref(segment, relevant_text)
        found_ref_in_string = ""

        is_perek_pasuk_ref, new_perek, new_pasuk = self.set_current_perek_pasuk(found_a_tag, relevant_text,
                                                                                next_segment_class, is_tanakh)

        # now create current_source based on real_title or based on self.current_parsha_ref
        if real_title:  # a ref to a commentator that we have in our system
            if new_pasuk:
                current_source = Source(u"{} {}:{}".format(real_title, new_perek, new_pasuk), next_segment_class)
            else:
                current_source = Source(u"{} {}".format(real_title, new_perek), next_segment_class)
        elif not real_title and is_tanakh:  # not a commentator, but instead a ref to the parsha
            current_source = Source(u"{} {}:{}".format(parser.en_sefer, new_perek, new_pasuk), "bible")
        # elif current_source.parshan_name != "bible":
        #     pass # look for mechilta? look for other books so not to get only Tanakh?
        elif len(relevant_text.split()) < 8:  # not found yet, look it up in library.get_refs_in_string
            found_ref_in_string = self._get_refs_in_string([relevant_text], next_segment_class,
                                                           add_if_not_found=False)
            #todo: I don't love the special casing for Mekhilta here... :(
            if re.search(u"מכילתא", relevant_text) and re.search(u"Exodus(.*)", found_ref_in_string):
                r = u"Mekhilta d'Rabbi Yishmael {}".format(re.search(u"Exodus(.*)", found_ref_in_string).group(1).strip())
                current_source = Source(r, next_segment_class)
            else:
                current_source = Source(found_ref_in_string, next_segment_class)
        else:
            current_source = Source("", next_segment_class)

        # finally set about_source_ref
        if current_source.get_ref():
            if not a_tag_is_entire_comment and found_ref_in_string == "" and len(relevant_text.split()) >= 6:
                # edge case where you found the ref but Nechama said something else in addition to the ref
                # so we want to keep the text
                current_source.about_source_ref = relevant_text
        elif found_a_tag:
            # found no reference but did find an a_tag so this is a ref so keep the text
            current_source.about_source_ref = relevant_text
            parser.index_not_found[parser.current_file_path].append(current_source.about_source_ref)
        else:
            current_source.about_source_ref = relevant_text

        current_source.parshan_id = 0 if len(next_segment_info)<2 else next_segment_info[1]
        return current_source

    def parse_ref_new(self, segment, relevant_text, next_segment_info): #bad try to put in parshan_id_table to read the parshan from the class number it has
        next_segment_class = next_segment_info[0]
        next_segment_class_id = None if len(next_segment_info)<2 else next_segment_info[1]
        real_title, found_a_tag, a_tag_is_entire_comment = self.get_a_tag_from_ref(segment, relevant_text)
        found_ref_in_string = ""

        # check if it's in Perek X, Pasuk Y format and set perek and pasuk accordingly
        is_tanakh = (relevant_text.startswith(u"פרק ") or relevant_text.startswith(u"פסוק ") or
                     relevant_text.startswith(u"פרקים ") or relevant_text.startswith(u"פסוקים "))
        is_perek_pasuk_ref, new_perek, new_pasuk = self.set_current_perek_pasuk(relevant_text, next_segment_class,
                                                                                is_tanakh)
        # now create current_source based on real_title or based on self.current_parsha_ref
        if next_segment_class == "parshan":
            try:
                parshan = parser.parshan_id_table[next_segment_class_id]
                current_source = Source(next_segment_class,
                                        u"{} on {} {}:{}".format(parshan, parser.en_sefer, new_perek, new_pasuk))
                current_source.parshan_name = parshan
            except KeyError:
                print "PARSHAN not in table", next_segment_class_id, relevant_text
                if real_title:  # a ref to a commentator that we have in our system
                    if new_pasuk:
                        current_source = Source(u"{} {}:{}".format(real_title, new_perek, new_pasuk), next_segment_class)
        if real_title and not next_segment_class == "parshan":  # a ref to a commentator that we have in our system
            if new_pasuk:
                current_source = Source(u"{} {}:{}".format(real_title, new_perek, new_pasuk), next_segment_class)
            else:
                current_source = Source(u"{} {}".format(real_title, new_perek), next_segment_class)
        elif not real_title and is_tanakh:  # not a commentator, but instead a ref to the parsha
            # if next_segment_class == "parshan":
            #     parshan = parser.parshan_id_table[next_segment_class_id]
            #     print "PARSHAN", parshan, next_segment_class_id
            #     current_source = Source(next_segment_class, u"{} on {} {}:{}".format(parshan, parser.en_sefer, new_perek, new_pasuk))
            #     current_source.parshan_name = parshan
            current_source = Source(u"{} {}:{}".format(parser.en_sefer, new_perek, new_pasuk), "bible")
        elif len(relevant_text.split()) < 8:  # not found yet, look it up in library.get_refs_in_string
            found_ref_in_string = self._get_refs_in_string([relevant_text], next_segment_class,
                                                           add_if_not_found=False)
            current_source = Source(next_segment_class, found_ref_in_string)
        else:
            current_source = Source("", next_segment_class)

        #finally set about_source_ref
        if current_source.get_ref():
            if not a_tag_is_entire_comment and found_ref_in_string == "" and len(relevant_text.split()) >= 6:
                # edge case where you found the ref but Nechama said something else in addition to the ref
                # so we want to keep the text
                current_source.about_source_ref = relevant_text
        elif found_a_tag:
            # found no reference but did find an a_tag so this is a ref so keep the text
            current_source.about_source_ref = relevant_text
            parser.index_not_found[parser.current_file_path].append(current_source.about_source_ref)
        else:
            current_source.about_source_ref = relevant_text

        return current_source

    def _get_refs_in_string(self, strings, next_segment_class, add_if_not_found=True):
        not_found = []
        for string in strings:
            orig = string
            string = "(" + string.replace(u"(", u"").replace(u")", u"") + ")"
            words_to_replace = [u"פרשה", u"*", chr(39), u"פרק", u"פסוק", u"השווה"]
            for word in words_to_replace:
                string = string.replace(u"ל" + word, u"")
                string = string.replace(word, u"")
            string = string.replace(u"  ", u" ").replace(u"\xa0", u" ")
            string = string.strip()
            refs = library.get_refs_in_string(string)
            if refs:
                return refs[0].normal()
            else:
                not_found.append(orig)
        # if len(not_found) == len(strings):
        #     if strings[-1] not in parser.ref_not_found.keys():
        #         parser.ref_not_found[strings[-1]] = 0
        #     parser.ref_not_found[strings[-1]] += 1
        return ""

    def set_current_perek(self, perek, is_tanakh, sefer):
        new_perek = str(getGematria(perek))
        if is_tanakh:
            if new_perek in self.possible_perakim:
                self.current_perek = str(new_perek)
                self.current_parsha_ref = ["bible", u"{} {}".format(sefer, new_perek)]
            else:
                print
        return True, new_perek, None
    

    def set_current_pasuk(self, pasuk, is_tanakh):
        pasuk = pasuk.strip()
        if len(pasuk)-1 > pasuk.find("-") > 0:  # is a range, correct it
            start = pasuk.split("-")[0]
            end = pasuk.split("-")[1]
            start = getGematria(start)
            end = getGematria(end)
            new_pasuk = u"{}-{}".format(start, end)
        else:  # there is a pasuk but is not ranged
            new_pasuk = str(getGematria(pasuk))

        if is_tanakh or self.RT_Rashi:
            poss_ref = self.pasuk_in_parsha_pasukim(new_pasuk)
            if poss_ref:
                self.current_perek = poss_ref.sections[0]
                self.current_pasuk = poss_ref.sections[1]# if not poss_ref.is_range() else u"{}-{}".format(poss_ref.sections[1], poss_ref.toSections[1])
            else:

                self.current_parsha_ref = ["bible", u"{} {}".format(parser.en_sefer, self.current_perek)]
        return True, self.current_perek, new_pasuk

    def set_current_perek_pasuk(self, a_tag, text, next_segment_class, is_tanakh=True):

        # text = re.search(u"(פרק(ים))",text)
        text = text if not a_tag else a_tag.text #this is useful for cases when pattern "Perek X Pasuk Y" occurs twice and one is inside a tag
        text = text.replace(u"פרקים", u"Perek").replace(u"פרק ", u"Perek ").replace(u"פסוקים", u"Pasuk").replace(
            u"פסוק ", u"Pasuk ").strip()
        digit = re.compile(u"^.{1,2}[\)|\.]").match(text)
        sefer = parser.en_sefer

        if digit:
            text = text.replace(digit.group(0), "").strip()
        text += " "  # this is hack so that reg ex works

        text = text.replace(u'\u2013', "-").replace(u"\u2011", "-")

        perek_comma_pasuk = re.findall("Perek (.{1,5}), (.*)", text)
        if not perek_comma_pasuk:
            perek_comma_pasuk = re.findall("Perek (.{1,5}),? Pasuk (.*)", text)
        perek = re.findall("Perek (.{1,5}\s)", text)
        pasuk = re.findall("Pasuk (.*)", text)
        assert len(perek) in [0, 1], "Perakim not len 0 or 1"
        assert len(pasuk) in [0, 1], "Pasukim not len 0 or 1"
        assert len(perek_comma_pasuk) in [0, 1], "Perek Pasuk not len 0 or 1"
        # if len(perek) == len(pasuk) == len(perek_comma_pasuk) == 0 and ("Pasuk" in text or "Perek" in text):
        #     pass

        if not perek_comma_pasuk:
            if perek:
                perek = perek[0]
                return self.set_current_perek(perek, is_tanakh, sefer)
            if pasuk:
                pasuk = pasuk[0]
                return self.set_current_pasuk(pasuk, is_tanakh)
        else:
            perek = perek_comma_pasuk[0][0]
            pasuk = perek_comma_pasuk[0][1]
            pasuk = pasuk.strip()
            new_perek = str(getGematria(perek))
            if len(pasuk)-1 > pasuk.find("-") > 0:  # is a range, correct it
                start = pasuk.split("-")[0]
                end = pasuk.split("-")[1]
                start = getGematria(start)
                end = getGematria(end)
                new_pasuk = u"{}-{}".format(start, end)
            else:  # there is a pasuk but is not ranged
                new_pasuk = str(getGematria(pasuk))

            if is_tanakh:
                poss_ref = self.pasuk_in_parsha_pasukim(new_pasuk, perakim=[new_perek])
                if poss_ref:
                    self.current_perek = poss_ref.sections[0]
                    self.current_pasuk = poss_ref.sections[1] #if not poss_ref.is_range() else u"{}-{}".format(poss_ref.sections[1], poss_ref.toSections[1])
                    # assert str(poss_ref.sections[0]) == new_perek or str(poss_ref.toSections[0]) == new_perek
                    # assert str(poss_ref.sections[1]) == new_pasuk or str(poss_ref.toSections[1]) == new_pasuk
                    self.current_parsha_ref = ["bible", u"{} {}".format(parser.en_sefer, self.current_perek)]
                else:
                    print
            return True, new_perek, new_pasuk
        return False, self.current_perek, self.current_pasuk


    def relevant_text(self, segment):
        if isinstance(segment, element.Tag):
            return segment.text
        return segment

    def rt_rashi_out(self, segment):
        classes = parser.important_classes[:] #todo: probbaly should be a list of classes of our Obj somewhere
        classes.extend(["question2", "question", "table"])
        bs_segs = segment.find_all(attrs={"class": classes})
        return bs_segs

    def find_all_p(self, segment):
        # return self.rt_rashi_out(segment)
        def skip_p(p):
            text_is_unicode_space = lambda x: len(x) <= 2 and (chr(194) in x or chr(160) in x)
            no_text = p.text == "" or p.text == "\n" or p.text.replace(" ", "") == "" or text_is_unicode_space(
                p.text.encode('utf-8'))
            return no_text and not p.find("img")

        ps = segment.find_all("p")
        new_ps = []
        temp_p = ""
        for p_n, p in enumerate(ps):
            if skip_p(p):
                continue
            elif len(p.text.split()) == 1 and re.compile(u"^.{1,2}[\)|\.]").match(
                    p.text):  # make sure it's in form 1. or ש.
                temp_p += p.text
            elif p.find("img"):
                img = p.find("img")
                if "pages/images/hard.gif" == img.attrs["src"]:
                    temp_p += "*"
                elif "pages/images/harder.gif" == img.attrs["src"]:
                    temp_p += "**"
            else:
                if temp_p:
                    temp_tag = BeautifulSoup("<p></p>", "lxml")
                    temp_tag = temp_tag.new_tag("p")
                    temp_tag.string = temp_p
                    temp_p = ""
                    p.insert(0, temp_tag)
                new_ps.append(p)

        return new_ps

    def pasuk_in_parsha_pasukim(self, new_pasuk, perakim=None):
        if perakim is None:
            perakim = self.possible_perakim
        for perek in perakim:
            possible_ref = Ref("{} ".format(parser.en_sefer) + perek + ":" + new_pasuk)
            if self.possible_pasukim.contains(possible_ref):
                return possible_ref
        return None

    def get_children_with_content(self, segment):
        # determine if the text of segment is blank or practically blank (i.e. just a \n or :\n\r) or is just empty space less than 3 chars
        children_w_contents = [el for el in segment.contents if
                               self.relevant_text(el).replace("\n", "").replace("\r", "").replace(": ", "").replace(
                                   ":", "") != "" and len(self.relevant_text(el)) > 2]
        return children_w_contents

    def check_for_blockquote_and_table(self, segments, level=2):
        new_segments = []
        # for i, segment in enumerate(segments):
        #     if segment.name == "blockquote" or (
        #             segment.name == "table" and segment.find_all(atrrs={"class": "RT_RASHI"})):
        #         test = segment
        #         while Section.get_Tags(test) == 1:
        #             test = Section.get_Tags(test)
        #         new_segments += test
        tables = ["table", "tr"]
        for i, segment in enumerate(segments):
            if isinstance(segment, element.Tag):
                class_ = segment.attrs.get("class", [""])[0]
            else:
                new_segments.append(segment)
                continue
            if segment.name == "blockquote":  # this is really many children so add them to list
                new_segments += self.get_children_with_content(segment)
            elif segment.name == "table" and class_ == "RT_RASHI":
                    new_segments += self.find_all_p(segment)
                    self.RT_Rashi = True
                        # question_in_question = [child for child in segment.descendants if
                        #                   child.name == "table" and child.attrs["class"][0] in ["question", "question2"]]
                        # RT_in_question = [child for child in segment.descendants if
                        #                   child.name == "table" and child.attrs["class"][0] in ["RT", "RTBorder"]]
            else:
                # no significant class and not blockquote or table
                new_segments.append(segment)

        level -= 1
        if level > -1:  # go level deeper unless level isn't > 0
            new_segments = self.check_for_blockquote_and_table(new_segments, level)
        return new_segments

    def format(self, comment):
        found_difficult = ""
        # digits = re.findall("\d+\.", comment)
        # for digit in set(digits):
        #     comment = comment.replace(digit, "<b>"+digit + " </b>")
        if "pages/images/hard.gif" in comment:
            found_difficult += "*"
        if "pages/images/harder.gif" in comment:
            found_difficult += "*"

        # we need to specifically keep these tags because the "text" property will remove them so we "hide" them with nosense characters
        tags_to_keep = ["u", "b"]
        comment = comment.replace("<u>", "$!u$").replace("</u>", "$/!u$")
        comment = comment.replace("<b>", "$!b$").replace("</b>", "$/!b$")
        text = BeautifulSoup(comment, "lxml").text

        text = text.strip()
        while "  " in text:
            text = text.replace("  ", " ")

        # following code makes sure "3.\nhello" becomes "3. hello"
        digit = re.match(u"^.{1,2}[\)|\.]", text)
        if digit:
            text = text.replace(digit.group(0), u"")
            text = text.strip()
            text = digit.group(0) + u" " + text

        # now get the tags back and remove nonsense chars
        text = text.replace("$!u$", "<u>").replace("$/!u$", "</u>")
        text = text.replace("$!b$", "<b>").replace("$/!b$", "</b>")
        text = text.replace("\n", "<br/>")

        return (found_difficult + text).strip()

class Nechama_Parser:
    def __init__(self, en_sefer, en_parasha, mode, add_to_title, catch_errors=False):
        if not os.path.isdir("reports/" + parsha):
            os.mkdir("reports/" + parsha)

        #matches, non_matches, index_not_found, and ref_not_found are all dict with keys being file path and values being list
        #of refs/indexes
        self.matches = {}
        self.non_matches = {}
        self.index_not_found = {}
        self.ref_not_found = {}
        self.to_match = True

        self.add_to_title = add_to_title
        self.catch_errors = catch_errors #crash upon error if False; if True, make report of each error
        self.mode = mode  # fast or accurate
        self.en_sefer = en_sefer
        self.en_parasha = en_parasha
        self._term_cache = {}
        self.important_classes = ["parshan", "midrash", "talmud", "bible", "commentary"]
        self.server = SEFARIA_SERVER
        self.segment_report = UnicodeWriter(open("segment_report.csv", 'a'))
        self.section_report = UnicodeWriter(open("section_report.csv", 'a'))
        now = datetime.datetime.now()
        now = now.strftime("%c")
        self.error_report = open("reports/{}/errors {}".format(en_parasha, now), 'w')
        self.has_parasha = [u"מכילתא"]
        self.term_mapping = {
            u"הכתב והקבלה": u"HaKtav VeHaKabalah, {}".format(self.en_sefer),
            u"חזקוני": u"Chizkuni, {}".format(self.en_sefer),
            u"""הנצי"ב מוולוז'ין""": u"Haamek Davar on {}".format(self.en_sefer),
            u"אונקלוס": u"Onkelos {}".format(self.en_sefer),
            u"שמואל דוד לוצטו": u"Shadal on {}".format(self.en_sefer),
            u"מורה נבוכים א'": u"Guide for the Perplexed, Part 1",
            u"מורה נבוכים ב'": u"Guide for the Perplexed, Part 2",
            u"מורה נבוכים ג'": u"Guide for the Perplexed, Part 3",
            u"תנחומא": u"Midrash Tanchuma, {}".format(self.en_sefer),
            u"בעל גור אריה": u"Gur Aryeh on {}".format(self.en_sefer),
            u"גור אריה": u"Gur Aryeh on {}".format(self.en_sefer), #todo: how does this mapping work? this name is the prime title
            u"""ראב"ע""": u"Ibn Ezra on {}".format(self.en_sefer),
            u"""וראב"ע:""": u"Ibn Ezra on {}".format(self.en_sefer),
            u"עקדת יצחק": u"Akeidat Yitzchak",
            u"תרגום אונקלוס": u"Onkelos {}".format(self.en_sefer),
            u"""רלב"ג""": u"Ralbag Beur HaMilot on Torah, {}".format(self.en_sefer),
            u"ר' אליהו מזרחי": u"Mizrachi, {}".format(self.en_sefer),
            u"""הרא"ם""": u"Mizrachi, {}".format(self.en_sefer),
            u"""ר' יוסף בכור שור""": u"Bekhor Shor, {}".format(self.en_sefer),
            u"בכור שור": u"Bekhor Shor, {}".format(self.en_sefer),
            u"אברבנאל": u"Abarbanel on Torah, {}".format(self.en_sefer),
            u"""המלבי"ם""": u"Malbim on {}".format(self.en_sefer),
            u"משך חכמה": u"Meshech Hochma, {}".format(self.en_parasha),
            u"רבנו בחיי": u"Rabbeinu Bahya, {}".format(self.en_sefer),
            u"מכילתא":u"Mekhilta d'Rabbi Yishmael"
            # u'רב סעדיה גאון': u"Saadia Gaon on {}".format(self.en_sefer) # todo: there is no Saadia Gaon on Genesis how does this term mapping work?
        }
        self.levenshtein = WeightedLevenshtein()
        self.missing_index = set()
        self.sec_ref_not_found = {}
        self.seg_ref_not_found = {}
        self.current_file_path = ""
        self.parshan_id_table = {
            '162': u"Rashi on {}".format(self.en_sefer),
            '6': u"Abarbanel on Torah, {}".format(self.en_sefer),  # Abarbanel_on_Torah,_Genesis
            '41': u'Or HaChaim on {}'.format(self.en_sefer),  # Or_HaChaim_on_Genesis
            '101': u'Mizrachi, {}'.format(self.en_sefer),
            '91': u"Gur Aryeh on ".format(self.en_sefer), #u"גור אריה",
            '32':u"Ralbag on {}".format(self.en_sefer), #u'''רלב"ג''', #todo, figure out how to do Beur HaMilot and reguler, maybe needs to be a re.search in the changed_ref method
            '29': u"Bekhor Shor, {}".format(self.en_sefer),#u"בכור שור",
            '238':u"Onkelos {}".format(self.en_sefer),#u"אונקלוס",
            '39': u'Ramban on {}'.format(self.en_sefer),# u'''רמב"ן''',
            '94': u"Shadal on {}".format(self.en_sefer),#u'''שד"ל''',
            '4': u"Ibn Ezra on {}".format(self.en_sefer),#u'''ראב"ע''',
            '198': u"HaKtav VeHaKabalah, {}".format(self.en_sefer),#u'''הכתב והקבלה''',
            '127': u"Radak on {}".format(self.en_sefer),#u'''רד"ק''',
            '37': u"Malbim on {}".format(self.en_sefer),#u'''מלבי"ם''',
            # '43': u'''בעל ספר הזיכרון''',
            '111': u"Akeidat Yitzchak", # u'''עקדת יצחק''',
            '28': u"Rabbeinu Bahya, {}".format(self.en_sefer),#u'''רבנו בחיי''',
            # '118':u'קסוטו',
            # '152':u'בנו יעקב',
            # '3':u'אבן כספי',
            '46':u"Haamek Davar on {}".format(self.en_sefer),
            # '104':u'''רמבמ"ן''',
            # '196':u'''בעל הלבוש אורה''',
            '66': u"Meshech Hochma, {}".format(self.en_parasha),
            # '51': u"ביאור - ר' שלמה דובנא"
        }


    def download_sheets(self):
        parshat_bereshit = ["1", "2", "30", "62", "84", "148", "212", "274", "302", "378", "451", "488", "527",
                            "563", "570", "581", "750", "787", "820", "844", "894", "929", "1021", "1034", "1125",
                            "1183", "1229", "1291", "1351", "1420"]
        start_after = 35
        for i in range(1500):
            if i <= start_after or str(i) in parshat_bereshit:
                continue
            print "downloading {}".format(i)
            sleep(3)
            headers = {
                'User-Agent': 'Mozilla/4.0 (Macintosh; Intel Mac OS X 11_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'}
            response = requests.get("http://www.nechama.org.il/pages/{}.html".format(i), headers=headers)
            if response.status_code == 200:
                with open("{}.html".format(i), 'w') as f:
                    f.write(response.content)
            else:
                print "No page at {}.html".format(i)

    def dict_from_html_attrs(self, contents):
        d = OrderedDict()
        for e in [e for e in contents if isinstance(e, element.Tag)]:
            if "id" in e.attrs.keys():
                d[e.attrs['id']] = e
            else:
                d[e.name] = e
        return d

    def get_score(self, words_a, words_b):

        str_a = u" ".join(words_a)
        str_b = u" ".join(words_b)
        dist = self.levenshtein.calculate(str_a, str_b, normalize=True)

        return dist

    def clean(self, s):
        s = unicodedata.normalize("NFD", s)
        s = strip_cantillation(s, strip_vowels=True)
        s = re.sub(u"(^|\s)(?:\u05d4['\u05f3])($|\s)", u"\1יהוה\2", s)
        s = re.sub(ur"[,'\":?.!;־״׳-]", u" ", s)
        s = re.sub(u'((?:^|\s)[\u05d0-\u05ea])\s+([\u05d0-\u05ea])', ur"\1\2", s)
        # s = re.sub(ur"-", u"", s)
        if not re.search(u'^\([^()]*(?:\)\s*)$', s):
            s = re.sub(ur"\([^)]+\)", u" ", s)
        # s = re.sub(ur"\([^)]+\)", u" ", s)
        # s = re.sub(ur"\((?:\d{1,3}|[\u05d0-\u05ea]{1,3})\)", u" ", s)  # sefaria automatically adds pasuk markers. remove them
        s = bleach.clean(s, strip=True, tags=()).strip()
        s = u" ".join(s.split())
        return s

    def tokenizer(self, s):
        return self.clean(s).split()


    def check_reduce_sources(self, comment, ref):
        new_ref = []
        n = len(comment.split())
        if n<=5:
            ngram_size = n
            max_words_between = 1
            min_words_in_match = n-2
        else:
            ngram_size = 3
            max_words_between = 4
            min_words_in_match = int(round(n*0.3))

        pm = ParallelMatcher(self.tokenizer, dh_extract_method=None, ngram_size=ngram_size, max_words_between=max_words_between, min_words_in_match=min_words_in_match,
        min_distance_between_matches=0, all_to_all=False, parallelize=False, verbose=False, calculate_score=self.get_score)
        if self.to_match:
            new_ref = pm.match(tc_list=[ref.text('he'), (comment, 1)], return_obj=True)
            new_ref = [x for x in new_ref if x.score > 80]
        return new_ref

    def change_ref_to_commentary(self, ref, comment_ind):
        ls = LinkSet(ref)
        commentators_on_ref = [x.refs[0] if x.refs[0] != ref.normal() else x.refs[1] for x in ls if Ref(x.refs[0]).is_commentary() or Ref(x.refs[1]).is_commentary()]
        for comm in commentators_on_ref:
            if comment_ind in Ref(comm).index.title:
                return Ref(comm).section_ref()
        if self.en_sefer in comment_ind:
            comment_ind = re.search(u'(.*?) on {}'.format(self.en_sefer), comment_ind).group(1)
            for comm in commentators_on_ref:
                if comment_ind in Ref(comm).index.title:
                    return Ref(comm).section_ref()
        return ref

    def try_parallel_matcher(self, current_source):
        try:
            try:
                if not current_source.get_sefaria_ref(current_source.ref):
                    ref2check = None
                else:
                    ref2check = current_source.get_sefaria_ref(current_source.ref) # used to be Ref(current_source.ref)
            except InputError:
                if u"Meshech Hochma" in current_source.ref:
                    ref2check = Ref(u"Meshech Hochma, {}".format(self.en_parasha))
            text_to_use = u""
            if self.mode == "fast":
                text_to_use = u" ".join(current_source.text.split()[0:15])
            elif self.mode == "accurate":
                text_to_use = current_source.text
            # todo: one Source obj for different Sefaria refs. how do we deal with this?
            if ref2check:
                # print ref2check.normal(), text_to_use
                text_to_use = self.clean(text_to_use) # .replace('"', '').replace("'", "")
                if len(text_to_use.split()) <= 1:
                    tc = ref2check.text('he').text if not isinstance(ref2check.text('he').text, list) else strip_cantillation(" ".join(ref2check.text('he').text))
                    if strip_cantillation(text_to_use, strip_vowels=True) in strip_cantillation(tc, strip_vowels=True).split():
                        current_source.ref = ref2check.normal()
                        # print current_source.ref
                    else:
                        print "it is one or less words and this is the wrong ref..."
                        return
                else:
                    matched = self.check_reduce_sources(text_to_use, ref2check) # returns a list ordered by scores of mesorat hashas objs that were found
                    changed_ref = ref2check  # ref2chcek might get a better ref but also might not...
                    if not matched:  # no match found
                        if current_source.parshan_id:
                            try:
                                parshan = parser.parshan_id_table[current_source.parshan_id]
                                # chenged_ref = Ref(u'{} {}'.format(parshan, u'{}:{}'.format(ref2check.sections[0], ref2check.sections[1]) if len(ref2check.sections)>1 else u'{}'.format(ref2check[0])))
                                changed_ref = self.change_ref_to_commentary(ref2check, parshan)
                                if changed_ref !=ref2check:
                                    matched = self.check_reduce_sources(text_to_use, changed_ref)
                            except KeyError:
                                print u"parshan_id_table is missing a key and value for {}, in {}, \n text {}".format(current_source.parshan_id, self.current_file_path, current_source.text)

                    if not matched: # still not matched...
                        if changed_ref.is_segment_level():
                            self.seg_ref_not_found[self.current_file_path].append(current_source)
                        else:
                            self.sec_ref_not_found[self.current_file_path].append(current_source)
                        print u"NO MATCH : {}".format(text_to_use)
                        self.non_matches[self.current_file_path].append(ref2check.normal())

                        # we dont want to link it since there's no match found so set the ref to empty and record the fixed ref ref2check in about_source_ref
                        current_source.about_source_ref = ref2check.he_normal()
                        current_source.ref = ""
                        return
                    self.matches[self.current_file_path].append(ref2check.normal())
                    current_source.ref = matched[0].a.ref.normal() if matched[0].a.ref.normal() != 'Berakhot 58a' else matched[
                        0].b.ref.normal()  # because the sides change

                    current_source.ref = matched[0].a.ref.normal() if matched[0].a.ref.normal() != 'Berakhot 58a' else matched[0].b.ref.normal()  # because the sides change
                    if ref2check.is_section_level():
                        print '** section level ref: '.format(ref2check.normal())
                    # print ref2check.normal(), current_source.ref
            else:
                print u"NO ref2check {}".format(current_source.parshan_name)
                if current_source.ref:
                    parser.ref_not_found[parser.current_file_path].append(current_source.ref)
                    current_source.ref = ""
        except AttributeError as e:
            print u'AttributeError: {}'.format(re.sub(u":$", u"", current_source.about_source_ref))
            parser.index_not_found[parser.current_file_path].append(current_source.about_source_ref)  # todo: would like to add just the <a> tag
        except IndexError as e:
            parser.index_not_found[parser.current_file_path].append(ref2check.normal())


    def organize_by_parsha(self, file_list_names):
        """
        The main BeautifulSoup reader function, that etrates on all sheets and creates the obj, probably should be in it's own file
        :param self:
        :return:
        """
        sheets = OrderedDict()
        for html_sheet in file_list_names:
            content = BeautifulSoup(open("{}".format(html_sheet)), "lxml")
            top_dict = dict_from_html_attrs(content.find('div', {'id': "contentTop"}).contents)
            parsha = top_dict["paging"].text
            shutil.move(html_sheet, "html_sheets/" + parsha)
        return sheets

    def bs4_reader(self, file_list_names, post = False, add_to_title = ""):
        """
        The main BeautifulSoup reader function, that etrates on all sheets and creates the obj, probably should be in it's own file
        :param self:
        :return:
        """
        sheets = OrderedDict()
        for html_sheet in file_list_names:
            try:
                parser.current_file_path = html_sheet
                parser.matches[parser.current_file_path] = []
                parser.non_matches[parser.current_file_path] = []
                parser.index_not_found[parser.current_file_path] = []
                parser.ref_not_found[parser.current_file_path] = []
                parser.seg_ref_not_found[parser.current_file_path] = []
                parser.sec_ref_not_found[parser.current_file_path] = []
                content = BeautifulSoup(open("{}".format(html_sheet)), "lxml")
                print "\n\n"
                print datetime.datetime.now()
                print html_sheet
                perek_info = content.find("p", {"id": "pasuk"}).text
                top_dict = dict_from_html_attrs(content.find('div', {'id': "contentTop"}).contents)
                # print 'len_content type ', len(top_dict.keys())
                sheet = Sheet(html_sheet, top_dict["paging"].text, top_dict["h1"].text, top_dict["year"].text, top_dict["pasuk"].text, parser.en_sefer, perek_info)
                sheets[html_sheet] = sheet
                body_dict = dict_from_html_attrs(content.find('div', {'id': "contentBody"}))
                sheet.div_sections.extend([v for k, v in body_dict.items() if re.search(u'ContentSection_\d', k)]) # check that these come in in the right order
                sheet.sheet_remark = body_dict['sheetRemark'].text
                sheet.parse_as_text()
                sheet.create_sheetsources_from_objsource()
                if post:
                    sheet.prepare_sheet(self.add_to_title)
            except Exception, e:
                if parser.catch_errors:
                    self.error_report.write(html_sheet+": ")
                    self.error_report.write(str(sys.exc_info()[0:2]))
                    self.error_report.write("\n")
                    self.error_report.write(traceback.format_exc())
                    self.error_report.write("\n\n")
                else:
                    raise
        return sheets


    def record_report(self):
        if not self.catch_errors:
            return

        now = datetime.datetime.now()
        now = now.strftime("%c")
        if not os.path.isdir("reports/{}".format(self.en_parasha)):
            os.mkdir("reports/{}".format(self.en_parasha))
        new_file = codecs.open("reports/{}/{} {}.txt".format(self.en_parasha, self.add_to_title, now), 'w', encoding='utf-8')
        parasha_matches = parasha_non_matches = parasha_total = parasha_ref_not_found = parasha_index_not_found = 0
        metadata_tuples = [(self.non_matches, "Non-matches", parasha_non_matches),
                           (self.ref_not_found, "Refs not found", parasha_ref_not_found),
                           (self.index_not_found, "Indexes not found", parasha_index_not_found)]
        for curr_file_path in self.matches.keys():
            sheet_matches = sheet_non_matches = sheet_total = 0
            new_file.write("\n\n"+curr_file_path)

            sources = self.matches[curr_file_path]
            if sources:
                new_file.write("\n{} - {}\n".format("Matches", len(sources)))
                new_file.write(u", ".join(sources))
                sheet_matches += len(sources)

            for tuple in metadata_tuples:
                metadata_dict, title, count = tuple
                sources = metadata_dict[curr_file_path]
                if sources:
                    new_file.write("\n{} - {}\n".format(title, len(sources)))
                    new_file.write(u", ".join(sources))
                    sheet_non_matches += len(sources)
                    count += len(sources)


            sheet_total = sheet_matches + sheet_non_matches
            if sheet_total: #something it's 0, why? Noach/5.html
                percent = 100.0*float(sheet_matches)/sheet_total
                new_file.write("\nSheet Total: {}".format(sheet_total))
                new_file.write("\nSheet Matches: {}".format(sheet_matches))
                new_file.write("\nSheet Percent Matched: {0:.2f}%".format(percent))
                parasha_matches += sheet_matches
                parasha_total += sheet_total
                parasha_non_matches += sheet_non_matches

        percent = 100.0*float(parasha_matches)/parasha_total
        new_file.write("\n\n\nParasha Total: {}".format(parasha_total))
        new_file.write("\nParasha Matches: {}".format(parasha_matches))
        new_file.write("\nParasha Percent Matched: {0:.2f}%".format(percent))

        new_file.close()


    def prepare_term_mapping(self):
        #growing collection of commands to run so that term_mapping can solely use en_sefer name instead of being hardcoded with things like "Bereshit" and "Bereishit"
        i = library.get_index("Midrash Tanchuma")
        node = i.nodes.children[2]
        node.add_title("Midrash Tanchuma, Genesis", 'en')
        i.save()
        i = library.get_index("Gur Aryeh on Bereishit")
        i.nodes.add_title("Gur Aryeh on Genesis", 'en')
        i.save()
        i = library.get_index("Gur Aryeh on Bamidbar")
        i.nodes.add_title("Gur Aryeh on Numbers", 'en')
        i.save()
        i = library.get_index("Meshech Hochma")
        node = library.get_index("Meshech Hochma").nodes.children[4]
        node.add_title("Chayei Sara", 'en')
        node = library.get_index("Meshech Hochma").nodes.children[6]
        node.add_title("Vayetzei", "en")
        node = library.get_index("Meshech Hochma").nodes.children[45]
        node.add_title("Korach", "en")
        i.save()
        t = Term().load({"titles.text": "Ki Tisa"})
        t.add_title(u'פרשת כי-תשא', 'he')
        t.save()
        t = Term().load({'titles.text': "Bechukotai"})
        t.add_title(u'פרשת בחקותי', 'he')
        t.save()
        t = Term().load({"titles.text": "Sh'lach"})
        t.add_title(u'פרשת שלח לך', 'he')
        t.save()
        t = Term().load({"titles.text": "Pinchas"})
        t.add_title(u'פרשת פינחס', 'he')
        t.save()


def dict_from_html_attrs(contents):
    d = OrderedDict()
    for e in [e for e in contents if isinstance(e, element.Tag)]:
        if "id" in e.attrs.keys():
            d[e.attrs['id']] = e
        else:
            d[e.name] = e
    return d


if __name__ == "__main__":
    # Ref(u"בראשית פרק ג פסוק ד - פרק ה פסוק י")
    # Ref(u"u'דברים פרק ט, ז-כט - פרק י, א-י'")
    genesis_parshiot = (u"Genesis", ["Bereshit", "Noach", "Lech Lecha", "Vayera", "Chayei Sara", "Toldot", 'Vayetzei', "Vayishlach", "Vayeshev", "Miketz", "Vayigash", "Vayechi"])
    exodus_parshiot = (u"Exodus", ["Shemot", "Vaera", "Bo", "Beshalach", "Yitro", "Mishpatim", "Terumah", "Tetzaveh", "Vayakhel", "Ki Tisa", "Pekudei"])
    leviticus_parshiot = (u"Leviticus", ["Vayikra", "Tzav", "Shmini", "Tazria", "Metzora", "Achrei Mot",
                        "Kedoshim", "Emor", "Behar", "Bechukotai"])
    numbers_parshiot = (u"Numbers", ["Bamidbar", "Nasso", "Beha'alotcha", "Sh'lach Lach", "Korach", "Chukat",
                        "Balak", "Pinchas", "Matot", "Masei"])
    devarim_parshiot = (u"Deuteronomy", ["Devarim", "Vaetchanan", "Eikev", "Re'eh", "Shoftim", "Ki Teitzei", "Ki Tavo",
                        "Nitzavim", "Vayeilech", "Ha'Azinu", "V'Zot HaBerachah"])
    combined_parshiot = ["Achrei Mot - Kedoshim", "Behar - Bechukotai", "Matot - Masei", "Nitzavim - Vayeilech", "Tazria - Metzora", "Vayakhel - Pekudei"]
    catch_errors = True

    which_parshiot = devarim_parshiot
    for parsha in which_parshiot[1]:
        book = which_parshiot[0]
        parser = Nechama_Parser(book, parsha, "fast", "trying to merge first time", catch_errors=catch_errors)
        parser.old = False
        parser.prepare_term_mapping() # must be run once locally and on sandbox
        #parser.bs4_reader(["html_sheets/Bereshit/787.html"], post=False)
        sheets = [sheet for sheet in os.listdir("html_sheets/{}".format(parsha)) if sheet.endswith(".html")]
        # anything_before = "7.html"
        # pos_anything_before = sheets.index(anything_before)
        # sheets = sheets[pos_anything_before:]
        sheets = parser.bs4_reader(["html_sheets/{}/{}".format(parsha, sheet) for sheet in sheets], post=False)
        if catch_errors:
            parser.record_report()



