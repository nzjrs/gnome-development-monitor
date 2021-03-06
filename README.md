GNOME Development Monitor
=========================
![Screenshot](http://github.com/nzjrs/gnome-development-monitor/raw/master/screenshot.jpg)

[Screenshot](http://github.com/nzjrs/gnome-development-monitor/raw/master/screenshot.jpg) 

Introduction
------------
GNOME Development Monitor is a simple graphical tool to follow the the development activity of projects hosted on the GNOME infrastructure.

By analysis of commit records (for the last N days) it is able to generate and display the following information;

* Aggregate statistics, like [GNOME Commit digest]("http://blogs.gnome.org/commitdigest/").
* For each project;
  * Changes to NEWS.
  * Changes to ChangeLog.
  * Easy viewing of the commit log.
  * New patches in bugzilla.
* Planet GNOME.

Usage
------
You need to have `pygtk`, `python-htmltmpl`, `python-dateutil` and `python-webkitgtk` installed. If the program crashes, freezes, or misbehaves then please upgrade your Webkit version. Usage is as follows;

    Usage: gnome.py [options]

    Options:
      -h, --help            show this help message and exit
      -s FILE, --source=FILE
                            read statistics from FILE [default: read from web]
      -d DAYS, --days=DAYS  the number of days to consider for statistics
                            [default: 5]
      -t [include|exclude|only], --translations=[include|exclude|only]
                            include translation commits in analysis [default:
                            exclude]

Implementation Details
-----------------------
*GNOME Development Monitor* is written in Python. In preparing the statistics the application does the following

1. Downloads the svn-commits-list mailing list archive for the current month.
2. Parses the html for that page and uses a regex to extract, for each commit, to which project it applies, what revision it is, and who commited it.
3. Adds the details of all commits into an sqlite database.
4. Performs a number of SQL queries on the DB to extract the summary information.
5. Displays a subset of the data to the user in a treeview.
6. Uses webkit to load the appropriate web page when the user requests more information on a project.




