__author__ = 'kmohamed'

# SETUP LOGGING
import logging
import logging.handlers

FORMATTER = logging.Formatter('%(name)s:%(levelname)s- %(message)s')
LOGFILE = '/tmp/vray2rs_log'
LOGGER = logging.getLogger('vray2redshift')
LOGGER.setLevel(logging.DEBUG)
# create rotating handler
ROT_HANDLER = logging.handlers.RotatingFileHandler(LOGFILE, backupCount=5)
ROT_HANDLER.setLevel(logging.DEBUG)
ROT_HANDLER.setFormatter(FORMATTER)
# create console handler
CONSOLE_HANDLER = logging.StreamHandler()
CONSOLE_HANDLER.setLevel(logging.INFO)
CONSOLE_HANDLER.setFormatter(FORMATTER)
LOGGER.addHandler(ROT_HANDLER)
LOGGER.addHandler(CONSOLE_HANDLER)

