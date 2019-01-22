import yaml
import sys
import logging
import argparse
from pythonjsonlogger import jsonlogger


logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

parser = argparse.ArgumentParser(description='Run the Proxy Load Balancer')
parser.add_argument('-c', '--config', help='yaml config file', required=True)
# TODO: Make overrides for server config values
args = parser.parse_args()

# TODO: Add lots of validation to the config inputs
with open(args.config, 'r') as stream:
    CONFIG = yaml.load(stream)


formatter = jsonlogger.JsonFormatter()

handler = logging.FileHandler('logs/proxy_request.json')
handler.setFormatter(formatter)

request_logger = logging.getLogger('proxy_request')
request_logger.setLevel(logging.INFO)
request_logger.addHandler(handler)
