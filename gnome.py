# SVN Commits Mailing List Parser
# For generating weekly commit digests
# (c) John Stowers
# Public Domain

import sqlite3
import urllib
import sgmllib
import re
import os.path
import dateutil.parser
import datetime

import htmltmpl
import pygooglechart

class HtmlRenderer:
    def __init__(self):
        self._data = []

    def add_data(self, **kwargs):
        self._data.append(kwargs)

    def render_html(self, limit=10):
        return self._data[0:min(len(self._data)-1,limit)]

    def render_chart(self, data_name, data_data, width=500,limit=20, bh=20):
        limit = min(len(self._data)-1,limit)

        chart = pygooglechart.StackedHorizontalBarChart(
                width=width,
                height=(limit*(bh+5))+10,
                )

        chart.set_bar_width(bh)
        #chart.set_colours(['00ff00'])
        chart.add_data(
                [self._data[l][data_data] for l in range(limit)]
        )
        chart.set_axis_labels(
                pygooglechart.Axis.LEFT,
                [self._data[l][data_name] for l in range(limit)]
        )
        chart.set_axis_range(
                pygooglechart.Axis.BOTTOM,
                *chart.data_x_range()
        )

        return chart.get_url()

    def render_text(self, limit=10):
        print "%10s\t: %d" % (name, freq)

class SVNCommitsParser(sgmllib.SGMLParser):
    """
    Parses svn-commits, looking for strings of the form
    <li><a name="01439" href="msg01439.html">gtk+ r21606 - in trunk: . gtk</a>&nbsp;&nbsp;cdywan</li>
    """
    def __init__(self, verbose=0):
        sgmllib.SGMLParser.__init__(self, verbose)

        self.updates = []
        self.msg = ""
        self.author = ""
        self.date = None
        self.inside_a_element = 0
        self.inside_li_element = 0
        self.inside_strong_element = 0
        self.misses = 0

    def start_li(self, attributes):
        self.inside_li_element = 1

    def end_li(self):
        self.inside_li_element = 0

    def start_strong(self, attributes):
        self.inside_strong_element = 1

    def end_strong(self):
        self.inside_strong_element = 0

    def parse(self, s):
        self.feed(s)
        self.close()

    def start_a(self, attributes):
        for name, value in attributes:
            if name == "href":
                self.inside_a_element = 1

    def end_a(self):
        self.inside_a_element = 0

    def handle_data(self, data):
        if self.inside_strong_element:
            self.date = dateutil.parser.parse(data)
            return

        if self.inside_li_element and self.inside_a_element:
            self.msg = data

        if self.inside_li_element and not self.inside_a_element:
            self.author = data

            if not self.msg:
                self.misses += 1
            elif self.msg in ("Home", "News", "Projects", "Art", "Support", "Development", "Community", "List archives", "Thread", "Author"):
                pass
            else:
                self.updates.append( (self.msg, self.author, self.date) )

    def get_stats(self):
        l = len(self.updates)
        return l,l+self.misses

class Stats:

    RE_EXP = "^([\w+\-]+) r([0-9]+) - (?:.*)(trunk|branches|tags)([a-zA-Z0-9/\:\.\-]*)"
    LIST_ARCHIVE_URL = "http://mail.gnome.org/archives/svn-commits-list/%s/date.html"

    def __init__(self, filename=None):
        if filename and os.path.exists(filename):
            self.f = open(filename, "r")
        else:
            filename = self.LIST_ARCHIVE_URL % datetime.date.today().strftime("%Y-%B")
            self.f = urllib.urlopen(filename)
        self.location = filename

        self.c = sqlite3.connect(":memory:", detect_types=sqlite3.PARSE_DECLTYPES).cursor()
        self.c.execute('''CREATE TABLE commits 
                        (project text, author text, rev int, 
                        branch text, message text, d timestamp)''')

        self.r = re.compile(self.RE_EXP)

        self.pr = HtmlRenderer()
        self.ar = HtmlRenderer()
        self.nr = HtmlRenderer()

    def collect_stats(self):
        data = self.f.read()
        self.f.close()

        parser = SVNCommitsParser()
        parser.parse(data)

        fail = []
        for msg, auth, date in parser.updates:
            n = self.r.match(msg)
            if not n:
                fail.append(msg)
                continue

            #break up the message and parse
            try:
                proj, rev, branch, message = n.groups()
                self.c.execute('''INSERT INTO commits 
                            (project, author, rev, branch, message, d) VALUES
                            (?, ?, ?, ?, ?, ?)''',
                            (proj, auth, int(rev), branch, message, date))

            except ValueError:
                fail.append(msg)

        hits, total = parser.get_stats()
        #print "PARSING PAGE: %s\nMatched %d/%d commit messages" % (self.location,hits,total)

    def generate_stats(self, num=5):
        #Authors
        self.c.execute('''
                SELECT author, COUNT(*) as c
                FROM commits 
                WHERE d >= datetime("now","-7 days")
                GROUP BY author 
                ORDER BY c DESC''')
        for name, freq in self.c:
            self.ar.add_data(author_name=name, author_freq=freq)

        #Projects
        self.c.execute('''
                SELECT project, COUNT(*) as c
                FROM commits 
                WHERE d >= datetime("now","-7 days") 
                GROUP BY project 
                ORDER BY c DESC''')
        for name, freq in self.c:
            self.pr.add_data(project_name=name, project_freq=freq)

        #New Projects
        self.c.execute('''
                SELECT project, author 
                FROM commits 
                WHERE rev < %s 
                AND d >= datetime("now","-7 days") 
                GROUP BY project''' % num)
        for name, author in self.c:
            self.nr.add_data(new_project_name=name, new_project_author=author)

    def render(self, format, name="gnome.tmpl"):
        if format == "html":

            template = htmltmpl.TemplateManager().prepare(name)
            tproc = htmltmpl.TemplateProcessor()

            tproc.set("date_generated", datetime.date.today().strftime("%Y-%B"))

            #Projects
            tproc.set("Projects", self.pr.render_html())
            tproc.set("project_chart", self.pr.render_chart("project_name","project_freq"))

            #Authors
            tproc.set("Authors", self.ar.render_html())
            tproc.set("author_chart", self.ar.render_chart("author_name","author_freq"))

            #Projects
            tproc.set("New", self.nr.render_html())

            # Print the processed template.
            print tproc.process(template)

        else:
            raise Exception("Format %s not supported" % format)

if __name__ == "__main__":
    import optparse

    parser = optparse.OptionParser()
    parser.add_option("-f", "--format",
                  type="choice", choices=("html", "text"), default="html",
                  help="output format [default: %default]")
    parser.add_option("-s", "--source",
                  help="read statistics from FILE [default: read from web]", metavar="FILE")
    options, args = parser.parse_args()

    s = Stats(options.source)
    s.collect_stats()
    s.generate_stats()
    s.render(options.format)

