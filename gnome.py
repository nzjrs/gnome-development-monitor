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
            url = self.LIST_ARCHIVE_URL % datetime.date.today().strftime("%Y-%B")
            self.f = urllib.urlopen(url)

        self.c = sqlite3.connect(":memory:", detect_types=sqlite3.PARSE_DECLTYPES).cursor()
        self.c.execute('''CREATE TABLE commits 
                        (project text, author text, rev int, 
                        branch text, message text, d timestamp)''')

        self.r = re.compile(self.RE_EXP)

    def generate_stats(self):
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
                
        print "PARSING PAGE:\nMatched %d/%d commit messages" % parser.get_stats()

    def get_authors(self, num=10):
        print "\nAUTHORS:"
        self.c.execute('''
                SELECT author, COUNT(*) as c
                FROM commits 
                WHERE d >= datetime("now","-7 days")
                GROUP BY author 
                ORDER BY c DESC 
                LIMIT %s''' % num)
        for name, freq in self.c:
            print "%10s\t: %d" % (name, freq)

    def get_active_projects(self, num=10):
        print "\nACTIVE PROJECTS:"
        self.c.execute('''
                SELECT project, COUNT(*) as c
                FROM commits 
                WHERE d >= datetime("now","-7 days") 
                GROUP BY project 
                ORDER BY c DESC 
                LIMIT %s''' % num)
        for name, freq in self.c:
            print "%20s\t: %d" % (name, freq)

    def get_new_projects(self, num=5):
        print "\nNEW PROJECTS:"
        self.c.execute('''
                SELECT project, author 
                FROM commits 
                WHERE rev < %s 
                AND d >= datetime("now","-7 days") 
                GROUP BY project''' % num)
        for name, author in self.c:
            print "%s by %s" % (name, author)

if __name__ == "__main__":
    import sys

    try:
        filename = sys.argv[1]
    except IndexError:
        filename = None

    s = Stats(filename)
    s.generate_stats()
    s.get_authors()
    s.get_active_projects()
    s.get_new_projects()

