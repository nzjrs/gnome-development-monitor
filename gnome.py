#!/usr/bin/env python

# Commits Mailing List Parser
# For generating weekly commit digests
# (c) John Stowers
# Public Domain

import sqlite3
import urllib
import urllib2
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
        #disable precompilation otherwise it tries to write the precompiled
        #template back to system dirs e.g. /usr/
        self.template = htmltmpl.TemplateManager(precompile=0, debug=0).prepare(template_name)
        self.tproc = htmltmpl.TemplateProcessor()
        #do not use UTC here, this is user displayed, local timezon
        self.tproc.set("date_generated", datetime.datetime.now().strftime("%Y-%B"))
        self.tproc.set("page_name", page_name)

    def render_variable(self, name, value):
        self.tproc.set(name, value)

    def render_template(self, *args, **kwargs):
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
    SECTION_TODAY_DATE = "today_date"
    SECTION_LAST_DATE = "last_date"

    def __init__(self):
        _HtmlRenderer.__init__(self, os.path.join(DATADIR,"summary.tmpl"), "GNOME Development Activity")
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

class CommitsMailParser(sgmllib.SGMLParser):
    """
    Parses commits, looking for strings of the form
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
        self.commit_number = 0

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
                #we dont get the exact time of the commit, so inorder to make sorting etc be
                #correct, add 1 second to the date for each line parsed on the page (as the
                #most recent commits are at the bottom of the page)
                self.updates.append( (self.msg, self.author, self.date + datetime.timedelta(0, self.commit_number)) )
                self.commit_number += 1

    def get_num_parsed_lines(self):
        return len(self.updates)

class Stats(threading.Thread, gobject.GObject):

    RE_EXP = "^\[([\w+\-\./]+)(: .*)?\] (.*)"
    RE_TRANSLATION_MESSAGE = ".*([Tt]ranslation|[Tt]ranslations]|[Ll]anguage).*"
    LIST_ARCHIVE_URL = "http://mail.gnome.org/archives/commits-list/%s/date.html"

    ALL_PROJECTS_URL = "http://git.gnome.org/repositories.txt"

    TRANSLATION_INCLUDE = "include"
    TRANSLATION_EXCLUDE = "exclude"
    TRANSLATION_ONLY = "only"
    TRANSLATION_CHOICES = (TRANSLATION_INCLUDE,TRANSLATION_EXCLUDE,TRANSLATION_ONLY)

    __gsignals__ = {
        "completed": (
            gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, []),
    }

    def __init__(self, filename, days, translations, includeall):

        threading.Thread.__init__(self)
        gobject.GObject.__init__(self)

        self.days = days
        self.filename = filename
        self.includeall = includeall

        #all the projects on the GNOME git servier, whether they have seen
        #any commits over the period or not
        self.allprojects = {}
        #projects with activity,
        #   name : [(branch_name, date, freq), ...]
        self.projects = {}
        #parse stats, (parsed ok, total, num translations)
        self.parse_stats = (0,0,0)

        conn = sqlite3.connect(":memory:", detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES, check_same_thread=False)
        #don't explode on unknown unicode
        conn.text_factory = lambda bin: bin.decode("utf8", "replace")
        self.c = conn.cursor()
        self.c.execute('''CREATE TABLE commits 
                        (project text, author text, 
                        branch text, message text, d timestamp, istranslation int)''')

        #in the database, istranslations is 0 or 1, so we can either include,
        #exclude or only consider translation commits depending on how we 
        #compare against this value in the SELECT clause, e.g
        # SELECT where istranslation ?? 0
        if translations == self.TRANSLATION_INCLUDE:
            self.includetranslations = ">="
        elif translations == self.TRANSLATION_EXCLUDE:
            self.includetranslations = "="
        elif translations == self.TRANSLATION_ONLY:
            self.includetranslations = ">"
        else:
            raise Exception("Invalid translation filter: %s" % translations)

        self.translations = translations
        print "TRANSLATIONS: %s" % self.translations

        self.r = re.compile(self.RE_EXP)
        self.rt = re.compile(self.RE_TRANSLATION_MESSAGE)
        self.rend = SummaryHtmlRenderer()

        self.todaydate = datetime.datetime.utcnow()
        self.lastdate = self.todaydate - datetime.timedelta(days=self.days)

    def _download_page(self, url, tries=5):
        i = 1
        msg = ""
        while i <= tries:
            try:
                print "DOWNLOADING PAGE: %s (attempt %d)" % (url, i)
                return urllib2.urlopen(urllib2.Request(url))
            except urllib2.HTTPError, e:
                msg = "The server couldn\'t fulfill the request. (error code: %s)" % e.code
            except urllib2.URLError, e:
                msg = "We failed to reach a server. (reason: %s)" % e.reason
            except Exception, e:
                msg = str(e)
            i += 1

        print "COULD NOT DOWNLOAD: %s (%s)" % (url, msg)
        return None

    def _get_archive_url(self, date):
        #we need to ignore the system locale because the list archive URLS
        #are in english
        MONTHS = (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December")

        return self.LIST_ARCHIVE_URL % ("%s-%s" % (
                            date.year,
                            MONTHS[date.month - 1]))

    def collect_stats(self):
        if self.includeall:
            f = self._download_page(self.ALL_PROJECTS_URL)
            if f:
                self.allprojects = [l.strip() for l in f.readlines()]

        if self.filename and os.path.exists(self.filename):
            files = [
                (open(self.filename, "r"), self.filename)
            ]
        else:
            filename = self._get_archive_url(self.todaydate)
            files = [
                (self._download_page(filename), filename)
            ]

            #if we are in the first n days of this month, and we require > n days of data
            #then also get the last month
            if self.todaydate.month != self.lastdate.month:
                filename = self._get_archive_url(self.lastdate)
                files.append(
                    (self._download_page(filename), filename)
                )


        numtranslations = 0
        for f, filename in files:
            if not f:
                continue

            data = f.read()
            f.close()

            parser = CommitsMailParser()
            parser.parse(data)

            fail = []
            for msg, auth, date in parser.updates:
                n = self.r.match(msg)
                if not n:
                    fail.append(msg)
                    continue

                #break up the message and parse
                try:
                    proj, series, message = n.groups()
                    try:
                        #use maxsplit=1 because some branch names are in the
                        #form foo/bar, e.g.
                        #"glib/wip/gapplication"
                        proj,branch = proj.split("/", 1)
                    except ValueError:
                        branch = "master"

                    #check if this is a translation commit
                    if self.rt.match(message):
                        numtranslations += 1
                        istranslation = 1
                    else:
                        istranslation = 0

                    self.c.execute('''INSERT INTO commits 
                                (project, author, branch, message, d, istranslation) VALUES
                                (?, ?, ?, ?, ?, ?)''',
                                (proj, auth, branch, message, date, istranslation))

                except ValueError:
                    print msg
                    fail.append(msg)

            total = parser.get_num_parsed_lines()
            parsed = total-len(fail)

            self.parse_stats = (parsed,total,numtranslations)

            print "PARSING PAGE: %s" % filename
            print "RESULTS: %s" % self.get_download_finished_message().capitalize()

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
        #notes:
        # MAX(d) is the most recent edit date
        # COUNT(*) is the number of commits when the GROUP by is applied
        # We sort first by the date, and then by the ROWID, as the rowid is
        #       monotonically increasing, larger rowids were lower on the
        #       page, and hence more recent commits
        i = []
        self.c.execute('''
                SELECT project, branch, MAX(d) as "d [timestamp]", COUNT(*) as c
                FROM commits 
                WHERE d >= datetime("now","-%d days") 
                AND istranslation %s 0 
                GROUP BY project, branch
                ORDER BY d DESC, ROWID DESC''' % (self.days,self.includetranslations))
        for name, branch, d, freq in self.c:
            i.append([name, freq, ""])
            try:
                self.projects[name].append((branch, d, freq))
            except KeyError:
                self.projects[name] = [(branch, d, freq)]

        #resort by number of commits
        i.sort(cmp=lambda x,y: cmp(y[1], x[1]))
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
        self.rend.render_variable(
                self.rend.SECTION_TODAY_DATE,
                self.todaydate.strftime("%x"))
        self.rend.render_variable(
                self.rend.SECTION_LAST_DATE,
                self.lastdate.strftime("%x"))
        return self.rend.render()

    def get_projects(self):
        projects = self.projects
        if self.includeall:
            for p in self.allprojects:
                if p not in projects:
                    projects[p] = []
        return projects

    def got_data(self):
        return self.parse_stats[0] > 0 and len(self.projects) > 0

    def get_download_message(self):
        return "Downloading %d day%s of development history" % (
                        self.days,
                        {
                            True:"s",
                            False:""
                        }[self.days > 1])

    def get_download_finished_message(self):

        def percentage(n,d):
            return 100.0 * (float(n)/d)

        nmatch,ntotal,ntrans = self.parse_stats
        msg = "matched %d/%d commit messages (%.2f%%%%), %%s %d translations (%.2f%%%%)" % (
            nmatch,ntotal,percentage(nmatch,ntotal),ntrans,percentage(ntrans,ntotal))
        print msg
        return msg % (
                    {
                        self.TRANSLATION_INCLUDE:"including",
                        self.TRANSLATION_EXCLUDE:"excluding",
                        self.TRANSLATION_ONLY:"only considering"
                    }[self.translations])

    def run(self):
        self.collect_stats()
        self.generate_stats()
        gobject.idle_add(gobject.GObject.emit,self,"completed")

class UI:

    BTNS = ("refresh_btn","commit_btn","news_btn","new_patches_btn","new_bugs_btn")
    CHANGELOG_STR = "http://git.gnome.org/browse/%(project)s/tree/ChangeLog"
    NEWS_STR = "http://git.gnome.org/browse/%(project)s/tree/NEWS"
    LOG_STR = "http://git.gnome.org/cgit/%(project)s/log?h=%(branch)s"
    NEW_PATCHES_STR = "https://bugzilla.gnome.org/page.cgi?id=patchreport.html&product=%(escaped_project)s&patch-status=&max_days=%(days)s"
    NEW_BUGS_STR = "https://bugzilla.gnome.org/buglist.cgi?product=%(escaped_project)s&bug_status=UNCONFIRMED&bug_status=NEW&bug_status=ASSIGNED&bug_status=REOPENED&chfield=[Bug creation]&chfieldfrom=%(last_date)s"

    #keep in sync with ui file
    PROJECT_NOTEBOOK_PAGE = 1

    def __init__(self, options):
        self.options = options

        #selected project
        self.project = None
        self.branch = None

        self.builder = _GtkBuilderWrapper(DATADIR, "gnome.ui")
        self.builder.connect_signals(self)

        loadingtxt = LoadingHtmlRenderer().render()

        #setup planet GNOME
        pg = webkit.WebView()
        pg.open("http://planet.gnome.org")
        self.builder.get_object("planetGnomeScrolledWindow").add(pg)
        self.builder.get_object("planetGnomeStopButton").connect(
                        "clicked",
                        self._stop_planetgnome,
                        pg)

        #setup summary page
        self.summaryWebkit = webkit.WebView()
        self.summaryWebkit.load_string(
                        loadingtxt,
                        "text/html", "utf-8", "commits:")
        self.builder.get_object("summaryScrolledWindow").add(self.summaryWebkit)

        self.sb = self.builder.get_object("statusbar1")
        sw = self.builder.get_object("projectScrolledWindow")
        self.projectWebkit = webkit.WebView()
        self.projectWebkit.load_string(
                        loadingtxt,
                        "text/html", "utf-8", "project:")
        sw.add(self.projectWebkit)

        self.model = gtk.TreeStore(str,int, object)
        self.tv = self.builder.get_object("treeview1")

        col = gtk.TreeViewColumn("Project Name", gtk.CellRendererText(), text=0)
        col.set_sort_column_id(0)
        self.tv.append_column(col)

        col = gtk.TreeViewColumn("Commits", gtk.CellRendererText(), text=1)
        col.set_sort_column_id(1)
        self.tv.append_column(col)

        rend = gtk.CellRendererText()
        date = gtk.TreeViewColumn("Last Commit", rend)
        date.set_sort_column_id(2)
        date.set_cell_data_func(rend, self._render_date)
        self.tv.append_column(date)
        self.model.set_sort_func(2, self._sort_dates)
        self.model.set_sort_column_id(2, gtk.SORT_ASCENDING)

        self.notebook = self.builder.get_object("notebook1")

        #make sure the treeview is visible
        self.builder.get_object("hpaned1").set_position(350)

        w = self.builder.get_object("window1")
        w.show_all()

    def _sort_dates(self, model, iter1, iter2):
        d1 = model.get_value(iter1, 2)
        d2 = model.get_value(iter2, 2)
        if d1 and d2:
            #newer
            if d1 > d2:
                return -1
            #older
            elif d2 > d1:
                return 1
        #equal
        return 0

    def _stop_planetgnome(self, btn, webview):
        webview.stop_loading()
        btn.set_sensitive(False)

    def _render_date(self, column, cell, model, iter_):
        d = model.get_value(iter_, 2)
        if d != datetime.datetime.min:
            cell.props.text = humanize_date_difference(now=self.stats.todaydate, otherdate=d)
        else:
            cell.props.text = "unknown"

    def _get_details_dict(self):
        today = self.stats.todaydate
        old = today-datetime.timedelta(days=self.stats.days)

        return {
            "project":self.project,
            "branch":self.branch,
            "escaped_project":urllib.quote(self.project),
            "today_date":today.strftime("%Y-%m-%d"),
            "last_date":old.strftime("%Y-%m-%d"),
            "days":self.stats.days,
        }

    def _statusbar_update(self, note):
        self.sb.push(
                self.sb.get_context_id("url"),
                note
        )

    def _open_project_url(self, url):
        self._statusbar_update(url)
        self.projectWebkit.open(url)
        self.notebook.set_current_page(self.PROJECT_NOTEBOOK_PAGE)

    def _get_selected_project(self):
        model,iter_ = self.tv.get_selection().get_selected()
        if model and iter_:
            if model.iter_depth(iter_) == 0:
                #if header is selected use the master branch
                self.project = model.get_value(iter_, 0)
                self.branch = "master"
            else:
                #otherwise use the shown branch
                self.branch = model.get_value(iter_, 0)
                self.project = model.get_value(model.iter_parent(iter_), 0)
        else:
            self._statusbar_update("Please select a project")
            self.project = None
            self.branch = None

        return self.project

    def on_commit_btn_clicked(self, *args):
        if self._get_selected_project():
            self._open_project_url(self.LOG_STR % self._get_details_dict())

    def on_news_btn_clicked(self, *args):
        if self._get_selected_project():
            self._open_project_url(self.NEWS_STR % self._get_details_dict())

    def on_new_patches_btn_clicked(self, *args):
        if self._get_selected_project():
            self._open_project_url(self.NEW_PATCHES_STR % self._get_details_dict())

    def on_new_bugs_btn_clicked(self, *args):
        if self._get_selected_project():
            self._open_project_url(self.NEW_BUGS_STR % self._get_details_dict())

    def on_refresh_btn_clicked(self, *args):
        self.refresh()

    def on_window1_destroy(self, *args):
        gtk.main_quit()

    def collect_stats_finished(self, stats):
        if not self.stats.got_data():
            self._statusbar_update("Download failed")
            return

        self._statusbar_update("Download finished, %s" % self.stats.get_download_finished_message())

        projects = self.stats.get_projects()
        for p in projects:
            newestdate = datetime.datetime.min
            totalcommits = 0
            for branch, d, commits in projects[p]:
                totalcommits += commits
                newestdate = max(d, newestdate)

            #add the project summary
            projiter = self.model.append(None, (p,totalcommits,newestdate))
            #add the branch summary
            for branch, d, commits in projects[p]:
                self.model.append(projiter, (branch,commits,d))

        self.tv.set_model(self.model)
        for i in self.BTNS:
            self.builder.get_object(i).set_sensitive(True)

        self.summaryWebkit.load_string(
                        self.stats.get_summary(), 
                        "text/html", "utf-8", "commits:"
        )

    def refresh(self):
        self.model.clear()
        for i in self.BTNS:
            self.builder.get_object(i).set_sensitive(False)
        self.stats = Stats(
                        filename=options.source,
                        days=options.days,
                        translations=options.translations,
                        includeall=options.all_projects)
        self.stats.connect("completed", self.collect_stats_finished)
        self._statusbar_update(self.stats.get_download_message())
        self.stats.start()

    def main(self):
        self.refresh()
        gtk.main()

if __name__ == "__main__":
    import optparse

    parser = optparse.OptionParser()
    parser.add_option("-s", "--source",
                  help="read statistics from FILE [default: read from web]", metavar="FILE")
    parser.add_option("-d", "--days",
                  type="int", default=3,
                  help="the number of days to consider for statistics [default: %default]")
    parser.add_option("-t", "--translations",
                  choices=Stats.TRANSLATION_CHOICES,
                  metavar="[%s]" % "|".join(Stats.TRANSLATION_CHOICES),
                  default=Stats.TRANSLATION_EXCLUDE,
                  help="include translation commits in analysis [default: %default]")
    parser.add_option("-a", "--all-projects",
                  help="include all GNOME projects, not just those with commits",
                  action="store_true")

    options, args = parser.parse_args()

    ui = UI(options)
    ui.main()


