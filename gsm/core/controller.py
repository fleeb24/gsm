
import sys, os
import json
import random
import traceback
import inspect
import yaml

from humpack import tset, tdict, tlist, containerify
from humpack import pack_member, unpack_member, json_pack, json_unpack
from .logging import GameLogger
from .state import GameState
from .table import GameTable
from .player import GameManager
from .phase import GameStack
from ..mixins import Named, Transactionable, Packable
from ..signals import PhaseComplete, SwitchPhase, GameOver, InvalidPlayerError, NoActiveGameError, InvalidKeyError, ClosedRegistryError, RegistryCollisionError, MissingValueError, MissingObjectError
from ..util import RandomGenerator, jsonify, get_printer
from ..io.registry import Game

from ..io import register_game

prt = get_printer(__name__)

class GameController(Named, Transactionable, Packable):
	
	def __init_subclass__(cls, register=False, name=None, info_path=None, **kwargs):
		super().__init_subclass__(**kwargs)
		
		cls.__home__ = os.path.dirname(inspect.getfile(cls))
		cls.config_files = tdict()
		
		config_dir = os.path.join(cls.__home__, 'config')
		
		if os.path.isdir(config_dir):
			prt.info(f'Config dir found for {cls.__name__} at {config_dir}')
			
			for fname in os.listdir(config_dir):
				name = '.'.join(fname.split('.')[:-1])
				path = os.path.join(config_dir, fname)
				cls.register_config(name, path)
			
		if register:
			Game(name=name, info_path=info_path)(cls)
			
	@classmethod
	def register_config(cls, name, path):
		if name in cls.config_files:
			prt.warning(f'Config file with name {name} is already registered in {cls.__name__}')
			
		cls.config_files[name] = path
	
	@classmethod
	def load_configs(cls):
		config = tdict()
		
		for name, path in cls.config_files.items():
			config[name] = containerify(yaml.load(open(path, 'r')))
		
		return config
	
	def __new__(cls, *args, **kwargs):
		new = super().__new__(cls)
		
		# meta values (neither for dev nor user) (not including soft registries - they dont change)
		new._tmembers = {'state', 'log', 'table', 'stack', 'players', 'end_info', '_advice', 'active_players',
		                 'keys', 'RNG', '_key_rng', '_images', '_advisor_images', 'config', 'player_names'}
		return new
	
	def __init__(self, name=None, debug=False, info_path=None, player_names=[],
	             manager=None, stack=None, table=None, log=None,
	             **settings):
		if name is None:
			# TODO: add suggestion about game name
			name = self.__class__.__name__
		super().__init__(name)

		if manager is None:
			manager = GameManager()
		if stack is None:
			stack = GameStack()
		if table is None:
			table = GameTable()
		if log is None:
			log = GameLogger()
		
		# Registries and managers
		self.players = manager
		self.stack = stack
		self.table = table
		
		self.config_files = tdict()
		
		# GameState
		self._pre_setup_complete = info_path # flag for pre setup
		self._in_progress = False # flag for registration to end
		self._in_transaction = False # flag for transactionable
		self.DEBUG = debug # flag for dev to use as needed
		self.player_names = tlist(player_names)
		
		self.keys = tdict() # a one time permission to call step() (with a valid action)
		self.RNG = RandomGenerator()
		self._images = tdict()
		self._advice = tdict()
		self._advisor_images = tdict()
		self._spec_image = None
		
		self.state = None
		self.active_players = None
		self.settings = containerify(settings)
		self.config = None
		self.end_info = None
		
		# Game components
		self.log = log
		
	def begin(self):
		if self.in_transaction():
			return
			self.commit()
		
		self._in_transaction = True
		for mem in self._tmembers:
			obj = self.__dict__[mem]
			if obj is not None:
				obj.begin()
		
	
	def in_transaction(self):
		return self._in_transaction
	
	def commit(self):
		if not self.in_transaction():
			return
		
		self._in_transaction = False
		for mem in self._tmembers:
			obj = self.__dict__[mem]
			if obj is not None:
				obj.commit()
		
	
	def abort(self):
		if not self.in_transaction():
			return
		
		self._in_transaction = False
		for mem in self._tmembers:
			obj = self.__dict__[mem]
			if obj is not None:
				obj.abort()
		
	
	def __pack__(self):
		
		data = {}
		
		# registries
		data['config_files'] = pack_member(self.config_files)
		
		# tmembers - arbitrary Packable instances
		for mem in self._tmembers:
			data[mem] = pack_member(self.__dict__[mem])
		
		data['name'] = pack_member(self.name)
		data['_in_progress'] = pack_member(self._in_progress)
		data['_in_transaction'] = pack_member(self._in_transaction)
		data['_pre_setup_complete'] = pack_member(self._pre_setup_complete)
		data['_spec_image'] = pack_member(self._spec_image)
		data['debug'] = pack_member(self.DEBUG)
		data['active_players'] = pack_member(self.active_players)
		
		return data
	
	def __unpack__(self, data):
		
		# load registries
		self.config_files = unpack_member(data['config_files'])
		
		# unpack tmembers
		for mem in self._tmembers:
			self.__dict__[mem] = unpack_member(data[mem])
			
		self.name = unpack_member(data['name'])
		self._in_transaction = unpack_member(data['_in_transaction'])
		self._in_progress = unpack_member(data['_in_progress'])
		self._pre_setup_complete = unpack_member(data['_pre_setup_complete'])
		self._spec_image = unpack_member(data['_spec_image'])
		self.DEBUG = unpack_member(data['debug'])
		self.active_players = unpack_member(data['active_players'])
	
	
	
	######################
	# Registration
	######################
	
	def register_player(self, name, **props):
		if self._in_progress:
			raise ClosedRegistryError
		self.players.register(name, **props)
	
	######################
	# Do NOT Override
	######################
		
	def _reset(self, player, seed=None):
		
		# reset all components
		
		if seed is None:
			seed = random.getrandbits(64)
		
		self.seed = seed

		self._key_rng = RandomGenerator(self.seed)
		self.RNG = RandomGenerator(self.seed)
		
		self.config.update(self._load_config())
		
		if self._pre_setup_complete is not None:
			info = None
			try:
				info = containerify(yaml.load(open(self._pre_setup_complete, 'r')))
			except:
				pass
			self._pre_setup(self.config, info)
		
		self.end_info = None
		self.active_players = tdict()
		
		
		# add players
		
		
		
		# init components
		
		self.state = GameState()
		self.log.reset(tset(self.players.names()))  # TODO: maybe this shouldnt just be the names
		self.table.reset(tset(self.players))
		self.stack.reset(self._set_phase_stack(self.config))
		
		# init game
		
		self._init_game(self.config)  # builds maps/objects
		self._in_progress = True
		
		# execute first player
		
		return self._step(player)
	
	def _step(self, player, group=None, action=None, key=None):  # returns python objs (but json readable)
		
		try:
			if player in self.players:
				player = self.players[player]
			else:
				raise InvalidPlayerError(player)
			
			if not len(self.stack):
				raise GameOver
			
			if self.active_players is None:
				raise NoActiveGameError('Call reset() first')
			
			if action is not None:
				if player not in self.active_players:
					return self._compose_msg(player)
				
				if key is None or key != self.keys[player]:
					raise InvalidKeyError
				
				action = self.active_players[player].verify(group, action) # action is a tuple with (action-group, (action-tuple))
			
			# start transaction
			self.begin()
			
			# prepare executing acitons
			
			# execute action
			while len(self.stack):
				phase = self.stack.pop()
				try:
					phase.execute(self, player=player, action=action)
					# get next action
					out = phase.encode(self)
				except PhaseComplete as intr:
					if not intr.transfer_action():
						action = None
				except SwitchPhase as intr:
					if intr.stacks():
						self.stack.push(phase)  # keep current phase around
					new = intr.get_phase()
					self.stack.push(new, **intr.get_phase_kwargs())
					if not intr.transfer_action():
						action = None
				else:
					self.stack.push(phase)
					break
			
			if not len(self.stack):
				raise GameOver
		
		except GameOver:
			self.commit()
			
			if self.end_info is None:
				self._clear_images()
				self.end_info = self._end_game()
				self._in_progress = False
			
			msg = self._compose_msg(player)
		
		except Exception as e:
			self.abort()
			# error handling
			
			msg = {
				'error': {
					'type': e.__class__.__name__,
					'msg': ''.join(traceback.format_exception(*sys.exc_info())),
				},
			}
		
		else:
			self.commit()
			# format output message
			
			self.active_players = tdict({p.name:opts for p, opts in out.items()})
			
			self._clear_images()
			
			msg = self._compose_msg(player)
		
		return msg
	
	######################
	# Must be Overridden
	######################
	
	# This function is implemented by dev to initialize the gamestate, and define player order
	def _init_game(self, config):
		raise NotImplementedError
	
	def _end_game(self): # return info to be sent at the end of the game
		raise NotImplementedError
	
	def _add_players(self, config, settings):
		raise NotImplementedError
		
	# must be implemented to define initial phase sequence
	def _set_phase_stack(self, config, settings):
		raise NotImplementedError
	
	######################
	# Optionally Overridden
	######################
	
	def cheat(self, code=None):
		pass
	
	def _clear_images(self):
		self._images.clear()
		self._advisor_images.clear()
		self._advice.clear()
		self._spec_image = None
	
	def _pre_setup(self, config, info=None):
		pass
	
	def _gen_key(self, player=None):
		key = hex(self._key_rng.getrandbits(64))[2:]
		if player is not None:
			self.keys[player] = key
		return key
	
	def _compose_msg(self, player=None, advisor=False):
		
		if player in self._images and not advisor:
			msg = json.loads(self._images[player])
		else:
			if self.end_info is not None:
				# game is already over
				msg = {
					'end': jsonify(self.end_info),
					'table': self.table.pull(), # full table
				}
			else:
				if player in self.active_players:
					msg = self.active_players[player].pull()
					if not advisor:
						msg['key'] = self._gen_key(player)
				elif player is not None:
					msg = {'waiting_for': list(self.active_players.keys())}
				else:
					msg = {}
				
				msg['players'] = self.players.pull(player)
				msg['table'] = self.table.pull(player)
				msg['phase'] = self.stack[0].name
				
			msg['log'] = self.log.pull(player)
			# log = self.log.pull(player)
			# if len(log):
			# 	msg['log'] = log
			
		if not advisor and player in self._advice:
			if 'advice' not in msg:
				msg['advice'] = []
			msg['advice'].extend(self._advice[player])
			del self._advice[player]
		
		if player is not None:
			if advisor:
				self._advisor_images[player] = json.dumps(msg)
			else:
				self._images[player] = json.dumps(msg)
		else:
			self._spec_image = json.dumps(msg)
		
		return msg
	
	######################
	# Dev functions (return obj)
	######################
	
	def create_phase(self, name, **kwargs):
		return self.stack.create(name, **kwargs)
	
	def create_object(self, obj_type, **spec): # this should delegate right away, all logic in GameTable
		return self.table.create(obj_type=obj_type, **spec)
	
	######################
	# User functions (return json str)
	######################
	
	def step(self, player, group=None, action=None, key=None):  # returns json bytes (str)
		return json.dumps(self._step(player=player, group=group, action=action, key=key))
	
	def give_advice(self, player, group, action, **info):
		if player not in self._advice:
			self._advice[player] = tlist()
			
		advice = info
		advice.update({'group':group, 'action':action})
		self._advice[player].append(advice)
	
	def reset(self, player, seed=None):
		return json.dumps(self._reset(player, seed))
	
	def get_status(self, player):
		if player not in self._images or player in self._advice:
			self._compose_msg(player)
		return self._images[player]
	
	def get_advisor_status(self, player):
		if player not in self._advisor_images:
			self._compose_msg(player, advisor=True)
		return self._advisor_images[player]
	
	def get_spectator_status(self):
		if self._spec_image is None:
			self._compose_msg()
		return self._spec_image
	
	def get_active_players(self):
		return json.dumps(list(self.active_players.keys()))
	
	def get_player(self, player):
		return json.dumps(jsonify(self.players[player]))
	
	def get_players(self):
		return json.dumps(list(self.players.names()))
	
	def get_table(self, player=None):
		return json.dumps(self.table.pull(player))
	
	def get_obj_types(self):
		return json.dumps(self.table.get_obj_types())
	
	def get_log(self, player=None, god_mode=False):
		log = self.log.get_full(player, god_mode)
		return json.dumps(jsonify(log))
	
	def get_UI_spec(self): # returns a specification for gUsIm - may be overridden to include extra data
		raise NotImplementedError # TODO: by default it should return contents of a config file
	
	def save(self):  # returns string
		data = json_pack(self)
		# data = str(Packable.pack(self))
		# print('key: {}'.format(self.RNG.random())) # testing
		return data
	
	def load(self, data):
		
		obj = json_unpack(data)
		
		# load registries
		self.config_files = obj.config_files
		
		# unpack tmembers
		for mem in self._tmembers:
			self.__dict__[mem] = obj.__dict__[mem]
		
		self.name = obj.name
		self._in_transaction = obj._in_transaction
		self._in_progress = obj._in_progress
		self.DEBUG = obj.DEBUG
	
	
	
	
	



