#!/bin/bash
##
## Quick Script to rough-monitor replication
##

EMAIL_TO=""
DEPLOYMENT_FLAG=""
SECONDS_BEHIND_THRESHOLD="1000"
SEND_ALERT=0
SKIP_REPLICATION_CHECK_FILE="/tmp/skip-replication-check"

[ -f "$SKIP_REPLICATION_CHECK_FILE" ] && echo "$SKIP_REPLICATION_CHECK_FILE found, exiting..." && exit 0

trim_to_lower() {
  local var="$1"; shift
  echo "$var" | tr '[:upper:]' '[:lower:]' | sed 's/^ *//; s/; */;/g'
}

send_email() {
    mail -t <<-EOF
To: $EMAIL_TO
Subject: $SUBJECT

$MESSAGE

Public IP: $PUBLIC_IP
Private IP: $PRIVATE_IP
Public Hostname: $PUBLIC_HOSTNAME
Date Checked: $DATE_CHECKED

EOF
}

while getopts "e:d:s:" OPT
do
    case "$OPT" in
        e) EMAIL_TO="$OPTARG" ;;
        d) DEPLOYMENT_FLAG="$OPTARG" ;;
        s) SECONDS_BEHIND_THRESHOLD="$OPTARG" ;;
        *) echo "Option: \"$OPT\" not supported" >&2 && exit 1 ;;
    esac
done

[ -z "$DEPLOYMENT_FLAG" ] && DEPLOYMENT_FLAG="UNSPECIFIED"
[ -z "$EMAIL_TO" ] && echo "EMAIL_TO is empty!" >&2 && exit 1

SECONDS_BEHIND_THRESHOLD="$((SECONDS_BEHIND_THRESHOLD+0))"
SLAVE_STATUS="$(mysql -e "SHOW SLAVE STATUS \G")"

SUBJECT_BASE="[$DEPLOYMENT_FLAG] - Replication Error"

IO="$(echo "$SLAVE_STATUS" | awk -F: ' $1 ~/Slave_IO_Running$/ { print $2 } ')"
SQL="$(echo "$SLAVE_STATUS" | awk -F: ' $1 ~/Slave_SQL_Running$/ { print $2 } ')"
SECONDS_BEHIND_MASTER="$(echo "$SLAVE_STATUS" | awk -F: ' $1 ~/Seconds_Behind_Master$/ { print $2 } ')"
LAST_ERROR="$(echo "$SLAVE_STATUS" | awk -F: ' $1 ~/Last_Error$/ { print $2 } ')"

if [ "$(trim_to_lower "$IO")" != "yes" -o "$(trim_to_lower "$SQL")" != "yes" ]; then
    SUBJECT="$SUBJECT_BASE :: Replication Down!"
    MESSAGE="
Replication is not running!

Slave_IO_Running: $IO
Slave_SQL_Running: $SQL
Last_Error: $LAST_ERROR

"
    SEND_ALERT=1
fi

if [ "$SECONDS_BEHIND_MASTER" -ge "$SECONDS_BEHIND_THRESHOLD" ]; then
    SUBJECT="$SUBJECT_BASE :: Replication Behind"
    MESSAGE="
Replication is running, but was behind the master at the time this was checked.

Seconds Behind the Master: $SECONDS_BEHIND_MASTER
Seconds Behind Threshold: $SECONDS_BEHIND_THRESHOLD (when we alert)
"
    SEND_ALERT=1
fi


if [ "$SEND_ALERT" -eq 1 ]; then
    PUBLIC_IP="$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)"
    PRIVATE_IP="$(curl -s http://169.254.169.254/latest/meta-data/local-ipv4)"
    PUBLIC_HOSTNAME="$(curl -s http://169.254.169.254/latest/meta-data/public-hostname)"
    DATE_CHECKED="$(date)"
    send_email
fi

exit $?


