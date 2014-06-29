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

if not HAS_COLOR:
    print("Unable to import colorama!")
    sys.exit(1)

PROCESS_THRESHOLD_WARN  = 100
PROCESS_THRESHOLD_CRIT  = 200

SLEEPER_THRESHOLD_WARN  = 30
SLEEPER_THRESHOLD_CRIT  = 75

USER_WHERE      = []

HOSTNAME        = None

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
    parser = argparse.ArgumentParser(description=color_val('MySQL Process list watcher & query killer.', Fore.YELLOW + Style.BRIGHT),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    con_opt_group   = parser.add_argument_group(color_val('Connection Options', Fore.YELLOW + Style.BRIGHT))
    config_group    = parser.add_argument_group(color_val('Configuration Options', Fore.YELLOW + Style.BRIGHT))
    kill_group      = parser.add_argument_group(color_val('Kill Options', Fore.RED + Style.BRIGHT))

    con_opt_group.add_argument('-H', '--host', dest='host', type=str, default='localhost',
        help='The host to get the process list from.')
    con_opt_group.add_argument('-p', '--port', dest='port', type=int, default=3306,
        help="The host's port.")
    con_opt_group.add_argument('-u', '--user', dest='user', type=str, default='root',
        help='The user to connect to the host as.')
    con_opt_group.add_argument('-P', '--pass', dest='passwd', type=str, default='',
        help='The password for authentication.')
    con_opt_group.add_argument('-ch', '--charset', dest='charset', type=str, default='utf8',
        help='Charset to use with the database.')

    ## ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    config_group.add_argument('-l', '--loop', dest='loop_second_interval', type=int, default=0,
        help='Time in seconds between getting the process list.')
    config_group.add_argument('-dft', '--default', dest='default', action='store_true',
        help='Run with defaults. Loop internal: 2 seconds, command like query or connect, order by time asc, id asc.')
    config_group.add_argument('-c', '--command', dest='command', type=str,
        help='Lookup processes running as this command.')
    config_group.add_argument('-s', '--state', dest='state', type=str,
        help='Lookup processes running in this state.')
    config_group.add_argument('-t', '--time', dest='time', type=int,
        help='Lookup processes running longer than the specified time in seconds.')
    config_group.add_argument('-d', '--database', dest='database', type=str,
        help='Lookup processes running against this database.')
    config_group.add_argument('-q', '--query', dest='query', type=str,
        help='Lookup processes where the query starts with this specification.')
    config_group.add_argument('-i', '--id', dest='id_only', action='store_true',
        help='Only print back the ID of the processes.')
    config_group.add_argument('-isr', '--ignore_system_user', dest='ignore_system_user', action='store_true',
        help="Ignore the 'system user'")
    config_group.add_argument('--debug', dest='debug', action='store_true',
        help='Provide debug output.')
    config_group.add_argument('-o', '--order_by', dest='order_by', type=str,
        help='Order the results by a particular column: "user", "db asc", "db desc", "time desc"...etc')

    ## ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    kill_group.add_argument('--kill', dest='kill', action='store_true',
        help='Kill the queries that we find.')
    kill_group.add_argument('-kt', '--kill_threshold', dest='kill_threshold', default=100,
        help="The kill threshold. If a number is provided, we'll need to hit that many total connections before killing queries. You can \
        set this to 'off' as well, which kills queries no matter how many connections there are.")
    kill_group.add_argument('-ka', '--kill_all', dest='kill_all', action='store_true',
        help="If this flag is provided, we'll attempt to kill everything, not only select queries. {0}".format(color_val("Use with caution!", Fore.RED + Style.BRIGHT))) 
    kill_group.add_argument('-ky', '--kill_yes', dest='kill_yes', action='store_true',
        help="If this is provided we won't stop to ask if you are sure that you want to kill queries.")
    kill_group.add_argument('-kl', '--kill_log', dest='kill_log', default='/var/log/killed_queries.log',
        help="Where to log killed queries to, granting permissions to write to this file.")

    return parser.parse_args()

def myp(d):
    print(json.dumps(d, indent=4))

def get_now_date():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def print_header():
    ct = get_connected_threads()
    header = "{0}".format(Fore.YELLOW) + "-"*40 + " " + "{0}".format(Fore.GREEN) + get_hostname() + \
        "{0} :: ".format(Fore.RESET) + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + \
        " :: Connected Threads: {0}{1}{2}".format(Fore.GREEN, ct, Fore.RESET) + \
        " {0}".format(Fore.YELLOW) + \
        "-"*40 + "{0}".format(Fore.RESET)
    print(header)
    print("{0}".format(Style.BRIGHT) + OUT_FORMAT.format("ID", "USER", "HOST", "DB", "COMMAND", "TIME", "STATE", "INFO") + "{0}".format(Style.RESET_ALL))

def sig_handler(signal, frame):
    if db:
        try:
            db.cursor_close()
            db.db_close()
        except MySQLdb.ProgrammingError:
            pass
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

def get_connected_threads():
    sql = "SHOW GLOBAL STATUS LIKE 'Threads_connected'"
    cur = db.query(sql)
    res = cur.fetchone()
    cur.close()
    if res and 'Value' in res:
        return res['Value']
    return 0

def get_hostname():
    global HOSTNAME

    if HOSTNAME: return HOSTNAME

    if args.host == 'localhost':
        ## local, just use socket.gethostname
        HOSTNAME = gethostname()
    else:
        ## we're going to ask the remote mysql server
        sql = "SELECT @@hostname AS hostname"
        cur = db.query(sql)
        res = cur.fetchone()
        cur.close()
        if res and 'hostname' in res:
            HOSTNAME = res['hostname']

    return HOSTNAME

def color_val(val, color):
    return "{0}{1}{2}".format(color, val, Style.RESET_ALL)

def record_kill(row):
    if os.path.exists(args.kill_log):
        if not os.access(args.kill_log, os.W_OK):
            return
    else:
        try:
            with open(args.kill_log, 'w+') as f:
                pass
        except IOError:
            print("Unable to create: {0}".format(args.kill_log))
            return

    kill_string = "{0} :: {1} :: {2}\n".format(get_now_date(), get_hostname(), ', '.join("%s: %s" % (k, v) for (k, v) in row.iteritems()))
    with open(args.kill_log, 'a') as f:
        f.write(kill_string)

def killah(results):
    ## ok. is it an integer and are the connected threads greater than the kill threshold ?
    try:
        args.kill_threshold = int(args.kill_threshold)
        ct = int(get_connected_threads())
        if ct < args.kill_threshold:
            print("Connected threads: {0}, Kill threshold: {1}. Not killing at this time".format(ct, args.kill_threshold), file=sys.stderr)
            return
    except ValueError:
        if args.kill_threshold.lower() != 'off':
            ## if we haven't set this to off, then no killing
            print("kill threshold was set but doesn't = off. Not killing at this time.", file=sys.stderr)
            return

    sql = "KILL %s"
    killed = 0
    for row in results:
        if not args.kill_all:
            if not row['info'].lower().startswith('select'):
                continue
        if db.query(sql, (row['id'],)):
            record_kill(row)
            killed += 1
    return killed

def process_row(results):
    if not args.id_only:
        num_reads           = num_writes = num_locked = num_closing = num_opening = num_past_long_query = num_sleepers = 0
        user_count          = {}
        long_query_time     = get_long_query_time()

    for row in results:
        if args.id_only:
            print(row['id'])
            continue

        if row['user'] not in user_count:
            user_count[row['user']] = 1
        else:
            user_count[row['user']] += 1

        if not row['info']: row['info'] = ''

        row['host'] = row['host'].split(':')[0]

        if READ_SEARCH.search(row['info']):
            num_reads   += 1
        if WRITE_SEARCH.search(row['info']):
            num_writes  += 1
        if LOCKED_SEARCH.search(row['state']):
            num_locked  += 1
        if OPENING_SEARCH.search(row['state']):
            num_opening += 1
        if CLOSING_SEARCH.search(row['state']):
            num_closing += 1
        if int(row['time']) > long_query_time:
            num_past_long_query += 1

        if row['command'].find('Sleep') != -1 or row['state'].find('sleep') != -1:
            num_sleepers += 1

        print(OUT_FORMAT.format(row['id'], row['user'], row['host'], row['db'], row['command'], row['time'], row['state'], row['info']))

    if args.id_only:
        return

    return {
        'num_reads':            num_reads,
        'num_writes':           num_writes,
        'num_locked':           num_locked,
        'num_closing':          num_closing,
        'num_opening':          num_opening,
        'num_sleepers':         num_sleepers,
        'num_past_long_query':  num_past_long_query,
        'user_count':           user_count
    }


def pslist(sql, counter):
    cur = db.query(sql)
    res = cur.fetchall()
    if res:
        num_processes       = cur.rowcount
        if args.kill:
            kills = killah(res)
            if kills:
                user_where_str = ' AND '.join(USER_WHERE)
                print("{0}".format(color_val(get_now_date() + " :: " + get_hostname() + \
                    " :: Killed: " + str(kills) + " (WHERE {0})".format(user_where_str), Fore.RED + Style.BRIGHT)))
            return

        if not args.id_only:
            print_header()

        _nums               = process_row(res)

        if not args.id_only:
            
            num_reads           = _nums['num_reads']
            num_writes          = _nums['num_writes']
            num_locked          = _nums['num_locked']
            num_closing         = _nums['num_closing']
            num_opening         = _nums['num_opening']
            num_sleepers        = _nums['num_sleepers']
            num_past_long_query = _nums['num_past_long_query']
            user_count          = _nums['user_count']

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
                .format(color_val(get_hostname(), Fore.GREEN), num_processes, num_sleepers, color_val(num_locked, Fore.CYAN), 
                    color_val(num_reads, Fore.CYAN), color_val(num_writes, Fore.CYAN), color_val(num_closing, Fore.CYAN), 
                    color_val(num_opening, Fore.CYAN), num_past_long_query))

            ## this is ok, but the next one sorts by occurrence
            #mystr = "{0}".format( ', '.join("%s: %s" % (k, "{0}".format(color_val(v, Fore.CYAN))) for (k, v) in user_count.iteritems()) )
            mystr = "{0}".format( ', '.join("%s: %s" % (k, "{0}".format(color_val(user_count[k], Fore.CYAN))) \
                for k in sorted(user_count, key=user_count.get, reverse=True)) )

            print("\t({0}) {1}".format(color_val("Users", Fore.GREEN), mystr))

            print()

        return True
    else:
        if counter % 4 == 0:
            print(color_val("{0} :: Still looking...".format(get_now_date()), Style.BRIGHT), file=sys.stderr)
        return False

def main():
    global USER_WHERE
    sql             = ''
    where           = []
    where_str       = ''
    order_by        = []
    order_by_str    = ''

    if args.kill:
        if not args.kill_yes:
            ans = raw_input(color_val("Are you sure you want to kill queries? ", Style.BRIGHT))
            if ans.lower() not in ('y', 'yes'):
                print("Ok, then only use --kill when you are you want to kill stuff.")
                sys.exit(0)

    select_fields   = ['id']

    if not args.id_only:
        select_fields += ['user', 'host', 'db', 'command', 'time', 'state', 'info']

    sql         = "SELECT {0} FROM processlist".format(', '.join(select_fields))

    if args.default:
        where.append("(command = 'Query' OR command = 'Connect')")
        args.loop_second_interval   = 3
        args.ignore_system_user     = True

        order_by    = [
            'time ASC',
            'id ASC'
        ]
    else:
        if args.command:
            where.append("command = '{0}'".format(args.command))
        if args.state:
            where.append("state = '{0}'".format(args.state))
        if args.time:
            where.append("time >= {0}".format(args.time))
        if args.database:
            where.append("db = '{0}'".format(args.database))
        if args.query:
            where.append("info LIKE '{0}%'".format(args.query))
        USER_WHERE = list(where)

    if args.kill and not where:
        print(color_val("ERROR: Cannot kill without specifying criteria!", Fore.RED + Style.BRIGHT))
        sys.exit(1)

    if args.kill and args.default:
        print(color_val("ERROR: Cannot kill using defaults!", Fore.RED + Style.BRIGHT))
        sys.exit(1)

    where.append("command != 'Binlog Dump'")
    where.append("(db != 'information_schema' OR db IS NULL)") ## confuses me why I had to add OR db IS NULL

    if args.ignore_system_user == True:
        where.append("user != 'system user'")

    if where:
        where_str       = ' WHERE {0}'.format(' AND '.join(where))

    if order_by:
        order_by_str    = ' ORDER BY {0}'.format(', '.join(order_by))

    sql = sql + where_str + order_by_str

    if args.debug:
        print("SQL: {0}".format(color_val(sql, Fore.CYAN)))

    if args.loop_second_interval > 0:
        counter = 0
        while True:
            counter += 1
            if pslist(sql, counter):
                counter = 0

            time.sleep(args.loop_second_interval)
    else:
        pslist(sql, 0)


signal.signal(signal.SIGINT, sig_handler)

args    = parse_args()
db      = mydb(args)

if __name__ == "__main__":
    main()




