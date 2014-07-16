mydba-tools
===========

Misc Tools to help with MySQL Tasks

**Note**

`mypsl` is the old process list watcher in perl. This script was written while I was at a company
where the tool ran in a specific environment. This one needs some attention, and I'm not a huge fan
of perl as it is which is why I started fresh with...

mypsl.py
--------
The new version in python.
The options are pretty much the same as the old perl version, it has some enhancements in output including color and more stats.
This version will run locally as well as connect to remote hosts granted you have
access to the server. If running locally, we'll attempt to use the mysql socket and default back to host/port. Remote connections
will obviously always use host/port. See `mypsl.py --help` to get a full list of options and how to use them.

External modules used
---------------------

| Module        | URL                                       | Required/Optional             |
| --------------|-------------------------------------------|:------------------------------|
| `PyMysql`     | https://pypi.python.org/pypi/PyMySQL      | Required                      |
| `colorama`    | https://pypi.python.org/pypi/colorama     | Required                      |
| `yaml`        | https://pypi.python.org/pypi/PyYAML       | Required if using --config    |
| `argcomplete` | https://pypi.python.org/pypi/argcomplete  | Not required - see docs       |

a little more on argcomplete
----------------------------
If argcomplete is installed, all options will autocomplete, but the `--config` option has more
functionality. If the `$HOME/.mypsl` directory exists and contains files, we'll auto-load the files available
and will auto-complete the filenames.
If you choose not to activate global completion, you will need to have this sourced into your environment (`.bashrc/.bash_profile`)
`eval "$(register-python-argcomplete mypsl.py)"`
Note: as explained on pypi, bash >= 4.2 is required, and your shell must be using it

`watch_replication.sh` is pretty much just a stub at the moment. As I have time and the need arises I'll update this one more.
