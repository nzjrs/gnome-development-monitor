#!/usr/bin/env python

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
import threading

import htmltmpl
import pygooglechart

import gobject
import gtk
import webkit

gtk.gdk.threads_init()

DATADIR = os.path.abspath(os.path.dirname(__file__))

def humanize_date_difference(now, otherdate=None, offset=None):
    if otherdate:
        dt = otherdate - now
        offset = dt.seconds + (dt.days * 60*60*24)

    #FIXME: The following sufficient, and the remaining code
    #is not necessary or useful until we can also parse
    #the hour of the commit
    if dt.days == 0:
        return "today"
    elif dt.days == -1:
        return "yesterday"
    else:
        return "%d days ago" % -dt.days

    if offset:
        delta_s = offset % 60
        offset /= 60
        delta_m = offset % 60
        offset /= 60
        delta_h = offset % 24
        offset /= 24
        delta_d = offset
    else:
        raise ValueError("Must supply otherdate or offset (from now)")

    if delta_d > 1:
        if delta_d > 6:
            date = now + datetime.timedelta(days=-delta_d, hours=-delta_h, minutes=-delta_m)
            return date.strftime('%A, %Y %B %m, %H:%I')
        else:
            wday = now + datetime.timedelta(days=-delta_d)
            return wday.strftime('%A')
    if delta_d == 1:
        return "Yesterday"
    if delta_h > 0:
        return "%dh%dm ago" % (delta_h, delta_m)
    if delta_m > 0:
        return "%dm%ds ago" % (delta_m, delta_s)
    else:
        return "%ds ago" % delta_s

class _GtkBuilderWrapper(gtk.Builder):
    def __init__(self, *path):
        gtk.Builder.__init__(self)
        self.add_from_file(os.path.join(*path))
        self._resources = {}

    def set_instance_resources(self, obj, *resources):
        for r in resources:
            setattr(obj, "_%s" % r.lower(), self.get_resource(r))

    def get_object(self, name):
        if name not in self._resources:
            w = gtk.Builder.get_object(self,name)
            if not w:
                raise Exception("Could not find widget: %s" % name)
            self._resources[name] = w

        return self._resources[name]

class _HtmlRenderer:
    def __init__(self, template_name, page_name):
        self._data = {}
        self.template = htmltmpl.TemplateManager().prepare(template_name)
        self.tproc = htmltmpl.TemplateProcessor()
        self.tproc.set("date_generated", datetime.date.today().strftime("%Y-%B"))
        self.tproc.set("page_name", page_name)

    def render_template(self):
        pass

    def render(self):
        self.render_template()
        return self.tproc.process(self.template)

class LoadingHtmlRenderer(_HtmlRenderer):
    def __init__(self):
        _HtmlRenderer.__init__(self, os.path.join(DATADIR,"loading.tmpl"), "Loading")

class SummaryHtmlRenderer(_HtmlRenderer):

    SECTION_PROJECT = "projects"
    SECTION_AUTHOR = "authors"

    def __init__(self):
        _HtmlRenderer.__init__(self, os.path.join(DATADIR,"summary.tmpl"), "GNOME Development Activity Summary")
        self._data = {}

    def _get_chart_url(self, section, data_name, data_data, width=500,limit=20, bh=20):
        limit = min(len(self._data[section])-1,limit)

        chart = pygooglechart.StackedHorizontalBarChart(
                width=width,
                height=(limit*(bh+5))+10,
                )

        chart.set_bar_width(bh)
        #chart.set_colours(['00ff00'])

        chart.add_data(
                [self._data[section][l][data_data] for l in range(limit)]
        )

        #the labels get applied in reverse for some reason
        labels = [self._data[section][l][data_name] for l in range(limit)]
        labels.reverse()
        chart.set_axis_labels(
                pygooglechart.Axis.LEFT,
                labels
        )

        chart.set_axis_range(
                pygooglechart.Axis.BOTTOM,
                *chart.data_x_range()
        )

        return chart.get_url()

    def render_template(self, limit=10):

        #Projects
        self.tproc.set("Projects", self.get_data(self.SECTION_PROJECT, limit))
        self.tproc.set("project_chart", self._get_chart_url(self.SECTION_PROJECT,"project_name","project_freq"))

        #Authors
        self.tproc.set("Authors", self.get_data(self.SECTION_AUTHOR, limit))
        self.tproc.set("author_chart", self._get_chart_url(self.SECTION_AUTHOR,"author_name","author_freq"))

        return self.tproc.process(self.template)

    def add_data(self, section, **kwargs):
        try:
            self._data[section].append(kwargs)
        except KeyError:
            self._data[section] = [kwargs]

    def get_data(self, section, limit):
        try:
            return self._data[section][0:min(len(self._data[section])-1,limit)]
        except KeyError:
            return []

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
                pass
            elif self.msg in ("Home", "News", "Projects", "Art", "Support", "Development", "Community", "List archives", "Thread", "Author"):
                pass
            else:
                self.updates.append( (self.msg, self.author, self.date) )

    def get_num_parsed_lines(self):
        return len(self.updates)

class Stats:

    RE_EXP = "^\[([\w+\-/]+)\] (.*)"
    RE_TRANSLATION_MESSAGE = "([Uu]pdated|[Aa]dded) .* ([Tt]ranslation)"
    LIST_ARCHIVE_URL = "http://mail.gnome.org/archives/svn-commits-list/%s/date.html"

    TRANSLATION_INCLUDE = "include"
    TRANSLATION_EXCLUDE = "exclude"
    TRANSLATION_ONLY = "only"
    TRANSLATION_CHOICES = (TRANSLATION_INCLUDE,TRANSLATION_EXCLUDE,TRANSLATION_ONLY)

    def __init__(self, filename, days, includetranslations):
        self.days = days
        self.filename = filename

        self.projects = []
        conn = sqlite3.connect(":memory:", detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES, check_same_thread=False)
        #don't explode on unknown unicode
        conn.text_factory = lambda bin: bin.decode("utf8", "replace")
        self.c = conn.cursor()
        self.c.execute('''CREATE TABLE commits 
                        (project text, author text, rev int, 
                        branch text, message text, d timestamp, istranslation int)''')

        #in the database, istranslations is 0 or 1, so we can either include,
        #exclude or only consider translation commits depending on how we 
        #compare against this value in the SELECT clause, e.g
        # SELECT where istranslation ?? 0
        if includetranslations == self.TRANSLATION_INCLUDE:
            self.includetranslations = ">="
        elif includetranslations == self.TRANSLATION_EXCLUDE:
            self.includetranslations = "="
        elif includetranslations == self.TRANSLATION_ONLY:
            self.includetranslations = ">"
        else:
            raise Exception("Invalid translation filter: %s" % includetranslations)

        print "TRANSLATIONS: Analysis %s" % includetranslations

        self.r = re.compile(self.RE_EXP)
        self.rt = re.compile(self.RE_TRANSLATION_MESSAGE)
        self.rend = SummaryHtmlRenderer()

    def collect_stats(self):
        if self.filename and os.path.exists(self.filename):
            files = [
                (open(self.filename, "r"), self.filename)
            ]
        else:
            today = datetime.date.today()
            last = today - datetime.timedelta(days=self.days)
            files = []

            filename = self.LIST_ARCHIVE_URL % today.strftime("%Y-%B")
            files.append(
                (urllib.urlopen(filename), filename)
            )

            #if we are in the first n days of this month, and we require > n days of data
            #then also get the last month
            if today.month != last.month:
                filename = self.LIST_ARCHIVE_URL % last.strftime("%Y-%B")
                files.append(
                    (urllib.urlopen(filename), filename)
                )

        numtranslations = 0
        for f, filename in files:
            print "DOWNLOADING PAGE: %s" % filename

            data = f.read()
            f.close()

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
                    rev = 1
                    proj, message = n.groups()
                    try:
                        proj,branch = proj.split("/")
                    except ValueError:
                        branch = "master"

                    #check if this is a translation commit
                    if self.rt.match(message):
                        numtranslations += 1
                        istranslation = 1
                    else:
                        istranslation = 0

                    self.c.execute('''INSERT INTO commits 
                                (project, author, rev, branch, message, d, istranslation) VALUES
                                (?, ?, ?, ?, ?, ?, ?)''',
                                (proj, auth, rev, branch, message, date, istranslation))

                except ValueError:
                    fail.append(msg)

            total = parser.get_num_parsed_lines()
            failed = len(fail)
            print "PARSING PAGE: %s" % filename
            print "RESULTS: Matched %d/%d commit messages (%d translations)" % (total-failed,total,numtranslations)

    def generate_stats(self):
        #Do in 2 steps because my SQL foo is not strong enough to
        #get the list of projects/authors per author/project

        #Get commits per authors
        i = []
        self.c.execute('''
                SELECT author, COUNT(*) as c
                FROM commits 
                WHERE d >= datetime("now","-%d days")
                AND istranslation %s 0 
                GROUP BY author 
                ORDER BY c DESC''' % (self.days,self.includetranslations))
        for name, freq in self.c:
            i.append([name, freq, ""])

        #Calculate which projects each author committed to
        for j in i:
            self.c.execute('''
                    SELECT project
                    FROM commits 
                    WHERE author = "%s" 
                    AND d >= datetime("now","-%d days") 
                    AND istranslation %s 0 
                    GROUP BY project''' % (j[0], self.days,self.includetranslations))
            j[2] = ", ".join([p for p, in self.c])
        for name, freq, projects in i:
            self.rend.add_data(
                    self.rend.SECTION_AUTHOR,
                    author_name=name, author_freq=freq, author_projects=projects)

        #Get commits per project
        i = []
        self.c.execute('''
                SELECT project, MAX(d) as "d [timestamp]", COUNT(*) as c
                FROM commits 
                WHERE d >= datetime("now","-%d days") 
                AND istranslation %s 0 
                GROUP BY project 
                ORDER BY d DESC''' % (self.days,self.includetranslations))
        for name, d, freq in self.c:
            #print "name: %s\n\tdate %s %s\n\t\tfreq: %s" % (name, d, type(d), freq)
            i.append([name, freq, ""])
            self.projects.append((name, d, freq))

        for j in i:
            self.c.execute('''
                    SELECT author
                    FROM commits 
                    WHERE project = "%s" 
                    AND d >= datetime("now","-%d days") 
                    AND istranslation %s 0 
                    GROUP BY author''' % (j[0], self.days, self.includetranslations))
            j[2] = ", ".join([p for p, in self.c])

        for name,freq, projects in i:
            self.rend.add_data(
                    self.rend.SECTION_PROJECT,
                    project_name=name, project_freq=freq, project_authors=projects)

    def get_summary(self):
        return self.rend.render()

    def get_projects(self):
        return self.projects

class UI(threading.Thread):

    BTNS = ("commit_btn","changelog_btn","news_btn","new_patches_btn")
    CHANGELOG_STR = "http://git.gnome.org/browse/%(project)s/tree/ChangeLog"
    NEWS_STR = "http://git.gnome.org/browse/%(project)s/tree/NEWS"
    LOG_STR = "http://git.gnome.org/cgit/%(project)s/log"
    NEW_PATCHES_STR = "https://bugzilla.gnome.org/page.cgi?id=patchreport.html&product=%(escaped_project)s&patch-status=&max_days=%(days)s"

    #keep in sync with ui file
    PROJECT_NOTEBOOK_PAGE = 1

    def __init__(self, stats):
        threading.Thread.__init__(self)
        self.stats = stats

        #selected project
        self.project = None

        self.builder = _GtkBuilderWrapper(DATADIR, "gnome.ui")
        self.builder.connect_signals(self)

        loadingtxt = LoadingHtmlRenderer().render()

        #setup planet GNOME
        pg = webkit.WebView()
        pg.open("http://planet.gnome.org")
        self.builder.get_object("planetGnomeScrolledWindow").add(pg)

        #setup summary page
        self.summaryWebkit = webkit.WebView()
        self.summaryWebkit.load_string(
                        loadingtxt,
                        "text/html", "iso-8859-15", "commits:")
        self.builder.get_object("summaryScrolledWindow").add(self.summaryWebkit)

        self.sb = self.builder.get_object("statusbar1")
        sw = self.builder.get_object("projectScrolledWindow")
        self.projectWebkit = webkit.WebView()
        self.projectWebkit.load_string(
                        loadingtxt,
                        "text/html", "iso-8859-15", "project:")
        sw.add(self.projectWebkit)

        self.model = gtk.ListStore(str,int, object)
        self.tv = self.builder.get_object("treeview1")
        self.tv.get_selection().connect("changed", self.on_selection_changed)

        col = gtk.TreeViewColumn("Project Name", gtk.CellRendererText(), text=0)
        col.set_sort_column_id(0)
        self.tv.append_column(col)

        col = gtk.TreeViewColumn("Commits", gtk.CellRendererText(), text=1)
        col.set_sort_column_id(1)
        self.tv.append_column(col)

        rend = gtk.CellRendererText()
        date = gtk.TreeViewColumn("Last Commit", rend)
        date.set_cell_data_func(rend, self._render_date)
        self.tv.append_column(date)

        self.notebook = self.builder.get_object("notebook1")

        w = self.builder.get_object("window1")
        w.show_all()

    def _render_date(self, column, cell, model, iter_):
        d = model.get_value(iter_, 2)
        cell.props.text = humanize_date_difference(now=self.time_started, otherdate=d)

    def _get_details_dict(self):
        today = datetime.date.today()
        old = today-datetime.timedelta(days=self.stats.days)

        return {
            "project":self.project,
            "escaped_project":urllib.quote(self.project),
            "today_date":today.strftime("%Y-%m-%d"),
            "last_date":old.strftime("%Y-%m-%d"),
            "days":self.stats.days,
        }

    def _open_project_url(self, url):
        self.sb.push(
                self.sb.get_context_id("url"),
                url
        )
        self.projectWebkit.open(url)
        self.notebook.set_current_page(self.PROJECT_NOTEBOOK_PAGE)

    def on_selection_changed(self, selection):
        model,iter_ = selection.get_selected()
        if model and iter_:
            self.project = model.get_value(iter_, 0)

    def on_commit_btn_clicked(self, *args):
        if self.project:
            self._open_project_url(self.LOG_STR % self._get_details_dict())

    def on_changelog_btn_clicked(self, *args):
        if self.project:
            self._open_project_url(self.CHANGELOG_STR % self._get_details_dict())

    def on_news_btn_clicked(self, *args):
        if self.project:
            self._open_project_url(self.NEWS_STR % self._get_details_dict())

    def on_new_patches_btn_clicked(self, *args):
        if self.project:
            self._open_project_url(self.NEW_PATCHES_STR % self._get_details_dict())


    def on_window1_destroy(self, *args):
        gtk.main_quit()

    def collect_stats_finished(self):
        for p,d,commits in self.stats.get_projects():
            self.model.append((p,commits,d))
        self.tv.set_model(self.model)
        for i in self.BTNS:
            self.builder.get_object(i).set_sensitive(True)

        self.summaryWebkit.load_string(
                        self.stats.get_summary(), 
                        "text/html", "iso-8859-15", "commits:"
        )

    def run(self):
        self.time_started = datetime.datetime.now()
        self.stats.collect_stats()
        self.stats.generate_stats()
        gobject.idle_add(self.collect_stats_finished)

    def main(self):
        self.start()
        gtk.main()

if __name__ == "__main__":
    import optparse

    parser = optparse.OptionParser()
    parser.add_option("-s", "--source",
                  help="read statistics from FILE [default: read from web]", metavar="FILE")
    parser.add_option("-d", "--days",
                  type="int", default=7,
                  help="the number of days to consider for statistics")
    parser.add_option("-t", "--translations",
                  choices=Stats.TRANSLATION_CHOICES,
                  metavar="[%s]" % "|".join(Stats.TRANSLATION_CHOICES),
                  default=Stats.TRANSLATION_EXCLUDE,
                  help="include translation commits in analysis [default: %default]")

    options, args = parser.parse_args()

    s = Stats(filename=options.source, days=options.days, includetranslations=options.translations)
    ui = UI(s)
    ui.main()


