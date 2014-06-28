#!/usr/bin/env python

from __future__ import print_function
import os
import sys
import argparse
import json
import time, datetime
import signal
import re
from socket import gethostname

## requires MySQLdb, colorama

try:
    import MySQLdb
    import MySQLdb.cursors
    HAS_MYSQLDB = True
except ImportError:
    HAS_MYSQLDB = False

try:
    from colorama import init, Fore, Style
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False


if not HAS_MYSQLDB:
    print("Unable to import MySQLdb!")
    sys.exit(1)

PROCESS_THRESHOLD_WARN  = 100
PROCESS_THRESHOLD_CRIT  = 200

SLEEPER_THRESHOLD_WARN  = 30
SLEEPER_THRESHOLD_CRIT  = 75

IGNORE_SYSTEM_USER      = True

HOSTNAME        = gethostname()

OUT_FORMAT      = "{0:<12}{1:16}{2:20}{3:22}{4:25}{5:<8}{6:28}{7:25}"

READ_SEARCH     = re.compile('^(show|select|desc)', re.IGNORECASE)
WRITE_SEARCH    = re.compile('^(insert|update|create|alter|replace|rename|delete)', re.IGNORECASE)
LOCKED_SEARCH   = re.compile('^(locked|waiting for table level lock|waiting for table metadata lock)', re.IGNORECASE)
OPENING_SEARCH  = re.compile('^opening table', re.IGNORECASE)
CLOSING_SEARCH  = re.compile('^closing table', re.IGNORECASE)

class mydb():
    conn            = None
    cursor          = None
    connect_args    = {}

    def __init__(self, args):
        self.connect_args = {
            'host':         args.host,
            'user':         args.user,
            'db':           'information_schema',
            'passwd':       args.passwd,
            #'unix_socket':  '',
            'charset':      args.charset,
            'cursorclass':  MySQLdb.cursors.DictCursor
        }

        MySQLdb.paramstyle = 'pyformat'

    def connect(self):
        try:
            self.conn = MySQLdb.connect(**self.connect_args)
        except MySQLdb.Error, e:
            print("{0}: {1}".format(e.args[0],e.args[1]))
            print("Unable to connect to mysql on {0}".format(self.connect_args['host']))

    def query(self, sql, args=[]):
        try:
            self.cursor = self.conn.cursor()
            if args:
                self.cursor.execute(sql, args)
            else:
                self.cursor.execute(sql)

        except (AttributeError, MySQLdb.OperationalError):
            self.connect()
            self.query(sql, args)

        if self.cursor:
            return self.cursor
        return False

    def cursor_close(self):
        if self.cursor:
            self.cursor.close()

    def db_close(self):
        if self.conn:
            self.conn.close()

def parse_args():
    parser = argparse.ArgumentParser(description='Arguments for mah script.')

    parser.add_argument('-H', '--host', dest='host', type=str, default='localhost',
        help='')
    parser.add_argument('-p', '--port', dest='port', type=int, default=3306,
        help='')
    parser.add_argument('-P', '--pass', dest='passwd', type=str, default='',
        help='')
    parser.add_argument('-u', '--user', dest='user', type=str, default='root',
        help='')
    parser.add_argument('-ch', '--charset', dest='charset', type=str, default='utf8',
        help='')

    parser.add_argument('-l', '--loop', dest='loop_second_interval', type=int, default=3,
        help='')
    parser.add_argument('-dft', '--default', dest='default', action='store_true',
        help='Run with defaults. Loop every 3 seconds...')

    return parser.parse_args()

def myp(d):
    print(json.dumps(d, indent=4))

def get_now_date():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def print_header():
    if HAS_COLOR:
        print("{0}".format(Fore.YELLOW) + "-"*40 + " " + "{0}".format(Fore.GREEN) + HOSTNAME + 
            "{0} :: ".format(Fore.RESET) + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " {0}".format(Fore.YELLOW) + 
            "-"*40 + "{0}".format(Fore.RESET))
        print("{0}".format(Style.BRIGHT) + OUT_FORMAT.format("ID", "USER", "HOST", "DB", "COMMAND", "TIME", "STATE", "INFO") + "{0}".format(Style.RESET_ALL))
    else:
        print("-"*40 + " " + HOSTNAME + " :: " + get_now_date() + " " + "-"*40)
        print(OUT_FORMAT.format("ID", "USER", "HOST", "DB", "COMMAND", "TIME", "STATE", "INFO"))

def sig_handler(signal, frame):
    if db:
        db.cursor_close()
        db.db_close()
    print()
    sys.exit(0)

def get_long_query_time():
    sql = "SHOW GLOBAL VARIABLES LIKE 'long_query_time'"
    cur = db.query(sql)
    res = cur.fetchone()
    cur.close()
    if res and 'Value' in res:
        return int(round(float(res['Value'])))
    return 0

def color_val(val, color):
    return "{0}{1}{2}".format(color, val, Style.RESET_ALL)

def pslist(sql, counter):
    cur = db.query(sql)
    res = cur.fetchall()
    if res:
        user_count          = {}
        long_query_time     = get_long_query_time()
        num_processes       = cur.rowcount
        num_reads           = num_writes = num_locked = num_closing = num_opening = num_past_long_query = num_sleepers = 0
        print_header()
        
        for r in res:
            if r['user'] not in user_count:
                user_count[r['user']] = 1
            else:
                user_count[r['user']] += 1

            if not r['info']: r['info'] = ''

            r['host'] = r['host'].split(':')[0]

            if READ_SEARCH.search(r['info']):
                num_reads   += 1
            if WRITE_SEARCH.search(r['info']):
                num_writes  += 1
            if LOCKED_SEARCH.search(r['state']):
                num_locked  += 1
            if OPENING_SEARCH.search(r['state']):
                num_opening += 1
            if CLOSING_SEARCH.search(r['state']):
                num_closing += 1
            if int(r['time']) > long_query_time:
                num_past_long_query += 1

            if r['command'].find('Sleep') != -1 or r['state'].find('sleep') != -1:
                num_sleepers += 1

            print(OUT_FORMAT.format(r['id'], r['user'], r['host'], r['db'], r['command'], r['time'], r['state'], r['info']))

        ## format total processes
        if num_processes >= PROCESS_THRESHOLD_CRIT:
            num_processes = color_val(num_processes, Fore.RED)
        elif num_processes >= PROCESS_THRESHOLD_WARN:
            num_processes = color_val(num_processes, Fore.YELLOW)
        else:
            num_processes = color_val(num_processes, Fore.CYAN)

        ## format the number of queries past the long query time
        if num_past_long_query > 0:
            num_past_long_query = color_val(num_past_long_query, Fore.RED)
        else:
            num_past_long_query = color_val(num_past_long_query, Fore.CYAN)

        ## format the number of sleepers
        if num_sleepers >= SLEEPER_THRESHOLD_CRIT:
            num_sleepers = color_val(num_sleepers, Fore.RED)
        elif num_sleepers >= SLEEPER_THRESHOLD_WARN:
            num_sleepers = color_val(num_sleepers, Fore.YELLOW)
        else:
            num_sleepers = color_val(num_sleepers, Fore.CYAN)

        print("\n\t({0}) PROCESSES: {1}, SLEEPERS: {2}, LOCKED: {3}, READS: {4}, WRITES: {5}, CLOSING: {6}, OPENING: {7}, PAST LQT: {8}"
            .format(color_val(HOSTNAME, Fore.GREEN), num_processes, num_sleepers, color_val(num_locked, Fore.CYAN), 
                color_val(num_reads, Fore.CYAN), color_val(num_writes, Fore.CYAN), color_val(num_closing, Fore.CYAN), 
                color_val(num_opening, Fore.CYAN), num_past_long_query))

        ## this is ok, but the next one sorts by occurrence
        #mystr = "{0}".format( ', '.join("%s: %s" % (k, "{0}".format(color_val(v, Fore.CYAN))) for (k, v) in user_count.iteritems()) )
        mystr = "{0}".format( ', '.join("%s: %s" % (k, "{0}".format(color_val(user_count[k], Fore.CYAN))) \
            for k in sorted(user_count, key=user_count.get, reverse=True)) )

        print("\t({0}) {1}".format(color_val("User Occurrences", Fore.GREEN), mystr))

        print()

        return True
    else:
        if counter % 4 == 0:
            print(color_val("{0} :: Still looking...".format(get_now_date()), Style.BRIGHT))
        return False

def main():

    sql             = ''
    where           = []
    where_str       = ''
    order_by        = []
    order_by_str    = ''

    sql         = "SELECT id, user, host, db, command, time, state, info FROM processlist"

    where       = [
        "command != 'Binlog Dump'",
        "(db != 'information_schema' OR db IS NULL)", ## confuses me why I had to add OR db IS NULL
    ]

    if IGNORE_SYSTEM_USER == True:
        where.append("user != 'system user'")

    order_by    = [
        'time ASC',
        'id ASC'
    ]

    if where:
        where_str       = ' WHERE {0}'.format(' AND '.join(where))

    if order_by:
        order_by_str    = ' ORDER BY {0}'.format(', '.join(order_by))

    sql = sql + where_str + order_by_str
    #print(sql)

    counter = 0
    while True:
        counter += 1
        if pslist(sql, counter):
            counter = 0

        time.sleep(args.loop_second_interval)


signal.signal(signal.SIGINT, sig_handler)

args    = parse_args()
db      = mydb(args)

if __name__ == "__main__":
    main()




