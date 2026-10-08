"""Run current strategy code with read-only source data and private metadata DB copy."""
import sys
from archive import setup, OUT
setup()
from strategies.nifty_options.replay import main
sys.argv = ['replay', '--manifest', str(OUT/'manifest.json'), '--broker', 'fyers', '--wait-for-download']
main()
