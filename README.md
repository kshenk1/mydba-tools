mydba-tools
===========

Misc Tools to help with MySQL Tasks

**Note**

`mypsl` is the old process list watcher in perl. This script was written while I was at a company
where the tool ran in a specific environment. This one needs some attention, and I'm not a huge fan
of perl as it is which is why I started fresh with...

`mypsl.py` is the new version in python. This is a work in progress, but is pretty solid at the moment.
The options are pretty much the same as the old perl version, it has some enhancements in output including color and more stats.
I'm not sure off hand about the perl version, but this version will run locally as well as connect to remote hosts granted you have
access to the server. If running locally, we'll attempt to use the mysql socket and default back to host/port. Remote connections
will obviously always use host/port.
