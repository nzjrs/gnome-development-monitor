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
import gtk.glade
import webkit

gtk.gdk.threads_init()

class HtmlRenderer:

    SECTION_PROJECT = "projects"
    SECTION_AUTHOR = "authors"
    SECTION_NEW = "new"

    def __init__(self, template_name="gnome.tmpl"):
        self._data = {}
        self.template = htmltmpl.TemplateManager().prepare(template_name)
        self.tproc = htmltmpl.TemplateProcessor()
        self.tproc.set("date_generated", datetime.date.today().strftime("%Y-%B"))

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

    def _render_template(self, limit):

        #Projects
        self.tproc.set("Projects", self.get_data(self.SECTION_PROJECT, limit))
        self.tproc.set("project_chart", self._get_chart_url(self.SECTION_PROJECT,"project_name","project_freq"))

        #Authors
        self.tproc.set("Authors", self.get_data(self.SECTION_AUTHOR, limit))
        self.tproc.set("author_chart", self._get_chart_url(self.SECTION_AUTHOR,"author_name","author_freq"))

        #Projects
        self.tproc.set("New", self.get_data(self.SECTION_NEW, limit))

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

    def render(self, limit=10):
        return self._render_template(limit)

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

    def __init__(self, filename, ignore_translation, days):
        self.ignore_translation = ignore_translation
        self.days = days
        self.filename = filename

        self.projects = []
        self.c = sqlite3.connect(":memory:", detect_types=sqlite3.PARSE_DECLTYPES, check_same_thread=False).cursor()
        self.c.execute('''CREATE TABLE commits 
                        (project text, author text, rev int, 
                        branch text, message text, d timestamp)''')

        self.r = re.compile(self.RE_EXP)
        self.rend = HtmlRenderer()

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


        for f, filename in files:
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
                    proj, rev, branch, message = n.groups()
                    if self.ignore_translation and "po" in message.split("/"):
                        pass
                    else:
                        self.c.execute('''INSERT INTO commits 
                                    (project, author, rev, branch, message, d) VALUES
                                    (?, ?, ?, ?, ?, ?)''',
                                    (proj, auth, int(rev), branch, message, date))

                except ValueError:
                    fail.append(msg)

            hits, total = parser.get_stats()
            print "PARSING PAGE: %s\nMatched %d/%d commit messages" % (filename,hits,total)

    def generate_stats(self):
        #Do in 2 steps because my SQL foo is not strong enough to
        #get the list of projects/authors per author/project

        #Authors
        i = []
        self.c.execute('''
                SELECT author, COUNT(*) as c
                FROM commits 
                WHERE d >= datetime("now","-%d days")
                GROUP BY author 
                ORDER BY c DESC''' % self.days)
        for name, freq in self.c:
            i.append([name, freq, ""])

        for j in i:
            self.c.execute('''
                    SELECT project
                    FROM commits 
                    WHERE author = "%s" 
                    AND d >= datetime("now","-%d days") 
                    GROUP BY project''' % (j[0], self.days))
            j[2] = ", ".join([p for p, in self.c])
        for name,freq, projects in i:
            self.rend.add_data(
                    self.rend.SECTION_AUTHOR,
                    author_name=name, author_freq=freq, author_projects=projects)

        #Projects
        i = []
        self.c.execute('''
                SELECT project, COUNT(*) as c
                FROM commits 
                WHERE d >= datetime("now","-%d days") 
                GROUP BY project 
                ORDER BY c DESC''' % self.days)
        for name, freq in self.c:
            i.append([name, freq, ""])

        for j in i:
            self.c.execute('''
                    SELECT author
                    FROM commits 
                    WHERE project = "%s" 
                    AND d >= datetime("now","-%d days") 
                    GROUP BY author''' % (j[0], self.days))
            j[2] = ", ".join([p for p, in self.c])

        for name,freq, projects in i:
            self.rend.add_data(
                    self.rend.SECTION_PROJECT,
                    project_name=name, project_freq=freq, project_authors=projects)

        #New Projects
        self.c.execute('''
                SELECT project, author 
                FROM commits 
                WHERE rev < 5 
                AND d >= datetime("now","-%d days") 
                GROUP BY project''' % self.days)
        for name, author in self.c:
            self.rend.add_data(
                self.rend.SECTION_NEW,
                new_project_name=name, new_project_author=author)

        #Record project min and max revision
        self.c.execute('''
                SELECT project, MAX(rev), MIN(rev)
                FROM commits 
                WHERE d >= datetime("now","-%d days") 
                GROUP BY project 
                ORDER BY project ASC''' % self.days)
        self.projects = [(p,ma,mi) for p, ma, mi  in self.c]

    def get_summary(self):
        return self.rend.render()

    def get_projects(self):
        return self.projects

class UI(threading.Thread):

    BTNS = ("commit_btn","changelog_btn","news_btn","summary_btn", "new_patches_btn")
    CHANGELOG_STR = "http://svn.gnome.org/viewvc/%(project)s/trunk/ChangeLog?r1=%(r1)s&r2=%(r2)s"
    NEWS_STR = "http://svn.gnome.org/viewvc/%(project)s/trunk/NEWS?r1=%(r1)s&r2=%(r2)s"
    LOG_STR = "http://svn.gnome.org/viewvc/%(project)s/?view=query&querysort=date&date=explicit&mindate=%(last_date)s&maxdate=%(today_date)s&limit_changes=100"
    NEW_PATCHES_STR = "http://bugzilla.gnome.org/reports/patch-report.cgi?product=%(project)s&patch-status=&max_days=%(days)s"

    def __init__(self, stats):
        threading.Thread.__init__(self)
        self.stats = stats

        #selected project (and revisions)
        self.proj = None
        self.min = None
        self.max = None

        self.widgets = gtk.glade.XML("ui.glade", "window1")
        self.widgets.signal_autoconnect(self)

        self.sb = self.widgets.get_widget("statusbar1")
        sw = self.widgets.get_widget("scrolledwindow1")
        self.webkit = webkit.WebView()
        sw.props.hscrollbar_policy = gtk.POLICY_AUTOMATIC
        sw.props.vscrollbar_policy = gtk.POLICY_AUTOMATIC
        sw.add(self.webkit)

        self.model = gtk.ListStore(str,int,int)
        self.tv = self.widgets.get_widget("treeview1")
        self.tv.append_column(gtk.TreeViewColumn("Project Name", gtk.CellRendererText(), text=0))
        self.tv.append_column(gtk.TreeViewColumn("Max Rev", gtk.CellRendererText(), text=1))
        self.tv.append_column(gtk.TreeViewColumn("Min Rev", gtk.CellRendererText(), text=2))

        self.tv.get_selection().connect("changed", self.on_selection_changed)

        self._open_url("http://planet.gnome.org")

        w = self.widgets.get_widget("window1")
        w.show_all()

    def _get_details_dict(self):
        today = datetime.date.today()
        old = today-datetime.timedelta(days=self.stats.days)

        #so we always see a diff
        if self.min == self.max:
            min_ = self.max -1
        else:
            min_ = self.min

        return {
            "project":self.proj,
            "r1":self.max,
            "r2":min_,
            "today_date":today.strftime("%Y-%m-%d"),
            "last_date":old.strftime("%Y-%m-%d"),
            "days":self.stats.days,
        }

    def _open_url(self, url):
        self.sb.push(
                self.sb.get_context_id("url"),
                url
        )
        self.webkit.open(url)

    def on_selection_changed(self, selection):
        model,iter_ = selection.get_selected()
        if model and iter_:
            self.proj = model.get_value(iter_, 0)
            self.max = model.get_value(iter_, 1)
            self.min = model.get_value(iter_, 2)

    def on_commit_btn_clicked(self, *args):
        if self.proj:
            self._open_url(self.LOG_STR % self._get_details_dict())

    def on_changelog_btn_clicked(self, *args):
        if self.proj:
            self._open_url(self.CHANGELOG_STR % self._get_details_dict())

    def on_news_btn_clicked(self, *args):
        if self.proj:
            self._open_url(self.NEWS_STR % self._get_details_dict())

    def on_summary_btn_clicked(self, *args):
        self.webkit.load_string(
                        self.stats.get_summary(), 
                        "text/html", "iso-8859-15", "commits:"
        )

    def on_new_patches_btn_clicked(self, *args):
        if self.proj:
            self._open_url(self.NEW_PATCHES_STR % self._get_details_dict())


    def on_window1_destroy(self, *args):
        gtk.main_quit()

    def collect_stats_finished(self):
        for p,ma,mi in self.stats.get_projects():
            self.model.append((p,ma,mi))
        self.tv.set_model(self.model)
        for i in self.BTNS:
            self.widgets.get_widget(i).set_sensitive(True)

    def run(self):
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
    parser.add_option("-t", "--include-translation",
                    action="store_false", default=True,
                    help="include translation commits (po) in statistics")

    options, args = parser.parse_args()

    s = Stats(filename=options.source, ignore_translation=options.include_translation, days=options.days)
    ui = UI(s)
    ui.main()


