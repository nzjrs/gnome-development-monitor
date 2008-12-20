#!/usr/bin/python
#
# chart - program to draw ascii charts
#
# Copyright 2006 Sony Corporation of America
#
# This program is available under the GNU General Public License (GPL)
# version 2 only.
#
# To do:
# * implement ticks
# * implement accumulated values

import sys
import os

def usage(rcode):
	prog_name = os.path.basename(sys.argv[0])
	print """Usage: %s [options]

 -a         Append values to a set of previously accumulated values
 -c         Clear accumulated values and exit
 -u         Specify upper limit of chart X range (auto-sensed by default)
 -l         Specify lower limit of chart X range (default 0)
 -t         Show tick marks
 -f <file>  Read values from a file instead of standard input
 -y         Specify maximum height of chart (default is 20 lines)
 -n         Use numbers instead of symbols for values
 -k <kind>  Specify kind of chart
 -h, --help Show this usage help 

Kind is one of: line, bar, cbar (cumulative bar), dbar (displaced bar), pie
 
By default, %s produces an ASCII chart by reading values from standard
input and writing a chart to standard output.

Data is provided as a set of space-separated values, with a data set
per line.  
""" % (prog_name, prog_name)
	sys.exit(rcode)

background_char = "."
collision_char = "*"
symbols = ["#","@","$","%","+","=","!","-"]
numbers = ["1","2","3","4","5","6","7","8"]

def plot_line(line, x1, x2, c, value):
	if x1>=len(line):
		return
	old_c = line[x2]
	# detect and plot collisions
	if old_c != background_char:
		c = collision_char
	# set this character in the line
	line = line[:x1] + c*(x2-x1+1) + line[x2+1:]
	return line

def main():
    chart_x = 78
    chart_h = 20
    symbol_list = symbols
    show_ticks = 0
    append_mode = 0
    clear_history = 0
    kind = "line"

    max_x = chart_x
    min_x = 0
    if '-h' in sys.argv or "--help" in sys.argv:
	usage(0)
    if '-u' in sys.argv:
	max_x = int(sys.argv[sys.argv.index('-u')+1])
    if '-l' in sys.argv:
	min_x = int(sys.argv[sys.argv.index('-l')+1])
    if '-y' in sys.argv:
	chart_h = int(sys.argv[sys.argv.index('-h')+1])
    if '-k' in sys.argv:
	kind = sys.argv[sys.argv.index('-k')+1]
	if kind not in ["line", "bar", "cbar"]:
		print "Error: unsupported chart kind '%s'" % kind
		usage(1)
    if '-n' in sys.argv:
	symbol_list = numbers
    if '-a' in sys.argv:
	append_mode = 1
    if '-c' in sys.argv:
	try:
		os.unlink("/tmp/chart_data")
	except:
		pass
	sys.exit(0)
    if '-t' in sys.argv:
	show_ticks = 1

    first_line = 1
    data = []

    if append_mode and not clear_history:
	# read old data, if any
	try:
		lines = open("/tmp/chart_data").readlines()
	except:
		lines = []
	new_line = sys.stdin.readlines()[0]
	lines.append(new_line)
    else:
        lines = sys.stdin.readlines()

    # truncate lines to the number requested
    lines = lines[-chart_h:]

    # determine the minimum and maximum values
    max_v = max_x
    min_v = 9999999999L
    for line in lines:
	values = line.split()
	old_v = 0
	for value in values:
		v = float(value)
		if kind == "cbar":
			old_v += v
			v = old_v
		if v > max_v:
			max_v = v
		if v < min_v:
			min_v = v

    print "max_v=", max_v
    print "min_v=", min_v

    # find nearest "natural" range for value
    # round to next highest exponent of 10
    
    print "chart_x=", chart_x

    for line in lines:
	values = line.split()
	if first_line:
		val_count = len(values)
	# plot values in line
	out_line = background_char*chart_x
	val_i = 0
	last_x = 0
	for value in values:
		# adjust value to x range
                # FIXTHIS - take into account min_v
		vf = float(value)
		xf = (vf / (max_v+1) ) * chart_x
		x = int(xf)
		
		# get symbol for value, based on value column
		c = symbol_list[val_i]
		if kind=="bar":
			x1 = 0
		elif kind=="cbar":
			x += last_x
			x1 = last_x
		else: # kind=="line"
			x1 = x

		x2 = x
		last_x = x
		out_line = plot_line(out_line, x1, x2, c, int(vf))
		val_i += 1
	print out_line

    # now print x-axis legend
    x_str = str(int(max_v))
    x_count = int(chart_x/(len(x_str)+3))
    out_line = (" "*(chart_x-len(x_str))) + x_str
    print out_line

    if append_mode:
	# re-write data
	dfile = open("/tmp/chart_data", "w")
	for line in lines:
		dfile.write(line)
	dfile.close()

if __name__=="__main__":
	main()

