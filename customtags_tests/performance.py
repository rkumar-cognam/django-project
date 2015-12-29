"""
Tests the performance of django builtin tags versus customtags implementations
of them.
"""
from _settings_patcher import *
from utils import pool, Benchmark
import sys

def format_num(num):
    try:
        return "%0.3f" % num
    except TypeError:
        return str(num)

def get_max_width(table, index):
    return max([len(format_num(row[index])) for row in table])

def pprint_table(out, table):
    col_paddings = []

    for i in range(len(table[0])):
        col_paddings.append(get_max_width(table, i))

    for row in table:
        # left col
        print >> out, row[0].ljust(col_paddings[0] + 1),
        # rest of the cols
        for i in range(1, len(row)):
            col = format_num(row[i]).rjust(col_paddings[i] + 2)
            print >> out, col,
        print >> out

def run(prnt, iterations):
    print
    print "Performance of django tags versus customtags. %s iterations." % iterations
    print
    pool.autodiscover()
    table = []
    table.append(["Tagname", "Django", "Classytags", "Ratio"])
    for tagname, data in pool:
        bench = Benchmark(data['tag']) 
        django = bench.django(iterations)
        classy = bench.classy(iterations)
        ratio = classy / django
        if tagname.startswith('ct_'):
            tagname = tagname[3:]
        table.append([tagname, django, classy, ratio])
    if prnt:
        pprint_table(sys.stdout, table)
    else:
        return table

def do_performance(iterations=10000):
    import optparse
    parser = optparse.OptionParser()
    options, args = parser.parse_args()
    run(True, iterations)

if __name__ == '__main__':
    iterations = 10000
    if len(args):
        try:
            iterations = int(args[0])
        except TypeError:
            pass
    do_performance(iterations)

