import math
import time
from os import system

while True:
	print('PPI Calculator')
	width = input('Insert width: ')
	height = input('Insert height: ')
	dim = input('Insert monitor size: ')
	print('PPI: ', math.sqrt(int(width)**2 + int(height)**2)/int(dim))
	time.sleep(1)
	system('clear')