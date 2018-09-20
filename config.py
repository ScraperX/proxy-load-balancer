import yaml
import logging
import argparse

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
