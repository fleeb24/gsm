
import sys, os, time
import random
from itertools import chain
from collections import OrderedDict
from .structures import Transactionable


_primitives = (str, int, float, bool)

class UnknownObject(Exception):
	pass

class Trackable(object):
	
	def __init__(self, tracker=None):
		super().__init__()
		self._tracker = tracker # usually should be set manually --> by GameObject
		
	def signal(self): # for tracking
		if self._tracker is not None:
			return self._tracker.signal()

# _container_id = 0

class Container(Trackable, Transactionable):
	def __init__(self, tracker=None):
		super().__init__(tracker=tracker)
		# global _container_id
		# self._id = _container_id
		# _container_id += 1
	
	# def __setattr__(self, key, item):
	# 	if isinstance(item, (Container,type(None)) + _primitives):
	# 		super().__setattr__(key, item)
	# 	else:
	# 		raise UnknownObject(key, item)
	
	def __setstate__(self, state):
		for key, value in state.items():
			if isinstance(value, dict) and '_type' in value:
				info = value
				value = eval(info['_type'] + '()')
				del info['_type']
				value.__setstate__(info)
			self.__dict__[key] = value
	
	def __getstate__(self):
		state = {}
		for key, value in self.__dict__.items():
			if isinstance(value, Container):
				info = value.__getstate__()
				info['_type'] = str(type(value).__name__)
			else:
				state[key] = value
		return state
	
	def copy(self):
		copy = type(self)()
		copy.__setstate__(self.__getstate__())
		return copy

_valid = {'_tracker', '_data', '_shadow'}

class tdict(Container, OrderedDict):
	def __init__(self, *args, **kwargs):
		super().__init__()
		self._data = OrderedDict(*args, **kwargs)
		self._shadow = None
		
	def in_transaction(self):
		return self._shadow is not None
		
	def begin(self):
		if self.in_transaction():
			self.abort()
			
		self._shadow = self._data
		
		for child in chain(self.keys(), self.values()):
			if isinstance(child, Transactionable):
				child.begin()
		
		self._data = self._data.copy()
		
	def commit(self):
		if not self.in_transaction():
			return
		
		for child in chain(self.keys(), self.values()):
			if isinstance(child, Transactionable):
				child.commit()
				
		self._shadow = None
	
	def abort(self):
		if not self.in_transaction():
			return
		for child in chain(self.keys(), self.values()):
			if isinstance(child, Transactionable):
				child.abort()
		
		self._data = self._shadow
		
	def update(self, other):
		self.signal()
		self._data.update(other)
	def fromkeys(self, keys, value=None):
		self.signal()
		self._data.fromkeys(keys, value)
		
	def clear(self):
		if len(self):
			self.signal()
		self._data.clear()
	
	def __len__(self):
		return len(self._data)
	
	def __contains__(self, item):
		return self._data.__contains__(item)
	def __reversed__(self):
		return self._data.__reversed__()
	
	def __iter__(self):
		return iter(self._data)
	def keys(self):
		return self._data.keys()
	def values(self):
		return self._data.values()
	def items(self):
		return self._data.items()
	
	def pop(self, key):
		self.signal()
		return self._data.pop(key)
	def popitem(self):
		self.signal()
		return self._data.popitem()
	def move_to_end(self, key, last=True):
		self.signal()
		self._data.move_to_end(key, last)
	
	def copy(self):
		copy = super().copy()
		copy._tracker = self._tracker
		return copy
	
	def __getstate__(self):
		state = {}
		data = {}
		for key, value in self.items():
			if isinstance(value, Container):
				value = value.__getstate__()
			data[key] = value
		
		state['_data'] = data
		if self._tracker is not None:
			state['_tracker'] = True#self._tracker._id
		state['_order'] = list(iter(self))
		state['_type'] = type(self).__name__
		# state['_id'] = self._id
		return state
	
	def __setstate__(self, state):
		assert type(self).__name__ == state['_type'], 'invalid type: {}'.format(type(self).__name__)
		
		if '_tracker' in state:
			assert self._tracker is not None, '_tracker must be set before calling __setstate__'
		
		data = state['_data']
		for key in state['_order']:
			value = data[key]
			if isinstance(value, dict) and '_type' in value:
				info = data[key]
				assert info['_type'] in _valid, 'invalid container type: {}'.format(info['_type'])
				value = eval(info['_type'] + '()')
				if '_tracker' in info:
					value._tracker = self._tracker
				value.__setstate__(info)
			self._data[key] = value
		self.signal()
	
	def get(self, k):
		return self._data.get(k)
	def setdefault(self, key, default=None):
		if key not in self:
			self.signal()
		self._data.setdefault(key, default)
	
	def __getitem__(self, item):
		return self._data[item]
	def __setitem__(self, key, value):
		if isinstance(value, Container):
			value._tracker = self._tracker
		self.signal()
		self._data[key] = value
	def __delitem__(self, key):
		self.signal()
		del self._data[key]
		
	def __getattr__(self, item):
		if item in _valid:
			return super().__getattribute__(item)
		return self.__getitem__(item)
	def __setattr__(self, key, value):
		if key in _valid:
			return super().__setattr__(key, value)
		return self.__setitem__(key, value)
	def __delattr__(self, item):
		if item in _valid:
			raise Exception('{} cannot be deleted'.format(item))
			# return super().__delattr__(item)
		return self.__getitem__(item)
	
	def __str__(self):
		return 'tdict({})'.format(', '.join([str(key) for key in iter(self)]))
	def __repr__(self):
		return 'tdict({})'.format(', '.join(['{}:{}'.format(repr(key), repr(value)) for key, value in self.items()]))
	

class tlist(Container, list):

	def __init__(self, *args, **kwargs):
		super().__init__()
		self._data = list(*args, **kwargs)
		self._shadow = None
	
	def in_transaction(self):
		return self._shadow is not None
	
	def begin(self):
		if self.in_transaction():
			self.abort()
		
		self._shadow = self._data
		
		for child in iter(self):
			if isinstance(child, Transactionable):
				child.begin()
		
		self._data = self._data.copy()
	
	def commit(self):
		if not self.in_transaction():
			return
		
		for child in iter(self):
			if isinstance(child, Transactionable):
				child.commit()
		
		self._shadow = None
	
	def abort(self):
		if not self.in_transaction():
			return
		for child in iter(self):
			if isinstance(child, Transactionable):
				child.abort()
		
		self._data = self._shadow
	
	def __getstate__(self):
		state = {}
		data = []
		for element in iter(self):
			if isinstance(value, Container):
				value = value.__getstate__()
			data.append(value)
		
		state['_data'] = data
		if self._tracker is not None:
			state['_tracker'] = True  # self._tracker._id
		state['_type'] = type(self).__name__
		return state
	
	def __setstate__(self, state):
		assert type(self).__name__ == state['_type'], 'invalid type: {}'.format(type(self).__name__)
		
		if '_tracker' in state:
			assert self._tracker is not None, '_tracker must be set before calling __setstate__'
		
		# self._id = state['_id']
		for element in state['_data']:
			if isinstance(element, dict) and '_type' in element:
				info = element
				assert info['_type'] in _valid, 'invalid container type: {}'.format(info['_type'])
				element = eval(info['_type'] + '()')
				if '_tracker' in info:
					element._tracker = self._tracker
				element.__setstate__(info)
			self._data.append(element)
		self.signal()
	
	def __getitem__(self, item):
		return self._data[item]
	def __setitem__(self, key, value):
		if isinstance(value, Container):
			value._tracker = self._tracker
		self.signal()
		self._data[key] = value
	def __delitem__(self, idx):
		self.signal()
		del self._data[idx]
		
	def count(self, object):
		return self._data.count(object)
	
	def append(self, item):
		self.signal()
		return self._data.append(item)
	
	def __contains__(self, item):
		return self._data.__contains__(item)
	
	def extend(self, iterable):
		self.signal()
		self._data.extend(iterable)
		
	def insert(self, index, object):
		self.signal()
		self._data.insert(index, object)
		
	def remove(self, value):
		self.signal()
		self._data.remove(value)
		
	def __iter__(self):
		return iter(self._data)
	def __reversed__(self):
		return self._data.__reversed__()
	
	def reverse(self):
		self.signal()
		self._data.reverse()
		
	def pop(self):
		self.signal()
		return self._data.reverse()
		
	def __len__(self):
		return len(self._data)
		
	def clear(self):
		self.signal()
		self._data.clear()
		
	def sort(self, key=None, reverse=False):
		self.signal()
		self._data.sort(key, reverse)
		
	def index(self, object, start=None, stop=None):
		self._data.index(object, start, stop)
	
	def __mul__(self, other):
		return self._data.__mul__(other)
	def __rmul__(self, other):
		return self._data.__rmul__(other)
	def __add__(self, other):
		return self._data.__add__(other)
	def __iadd__(self, other):
		self.signal()
		self._data.__iadd__(other)
	def __imul__(self, other):
		self.signal()
		self._data.__imul__(other)
	
	
class tset(Container):
	
	def __init__(self, iterable=[]):
		super().__init__()
		self._data = OrderedDict()
		self._data.fromkeys(iterable)
		self._shadow = None
	
	def in_transaction(self):
		return self._shadow is not None
	
	def begin(self):
		if self.in_transaction():
			self.abort()
		
		self._shadow = self._data
		
		for child in iter(self):
			if isinstance(child, Transactionable):
				child.begin()
		
		self._data = self._data.copy()
	
	def commit(self):
		if not self.in_transaction():
			return
		
		for child in iter(self):
			if isinstance(child, Transactionable):
				child.commit()
		
		self._shadow = None
	
	def abort(self):
		if not self.in_transaction():
			return
		for child in iter(self):
			if isinstance(child, Transactionable):
				child.abort()
		
		self._data = self._shadow
	
	def __getstate__(self):
		state = {}
		data = []
		for x in iter(self):
			if isinstance(x, Container):
				x = x.__getstate__()
			data.append(x)
		
		state['_data'] = {'set':data}
		if self._tracker is not None:
			state['_tracker'] = True  # self._tracker._id
		state['_type'] = type(self).__name__
		return state
	
	def __setstate__(self, state):
		assert type(self).__name__ == state['_type'], 'invalid type: {}'.format(type(self).__name__)
		
		if '_tracker' in state:
			assert self._tracker is not None, '_tracker must be set before calling __setstate__'
		
		# self._id = state['_id']
		for element in state['_data']['set']:
			if isinstance(element, dict) and '_type' in element:
				info = element
				assert info['_type'] in _valid, 'invalid container type: {}'.format(info['_type'])
				element = eval(info['_type'] + '()')
				if '_tracker' in info:
					element._tracker = self._tracker
				element.__setstate__(info)
			self._data.add(element)
		self.signal()

	def __hash__(self):
		return id(self)
	def __eq__(self, other):
		return id(self) == id(other)
		



class GameState(Container):
	pass

class GameObject(Container):
	
	def __init__(self, name=None, obj_type=None, **kwargs):
		super().__init__()
		self.name = name
		self.obj_type = obj_type
		self.__dict__.update(kwargs)
		
		global _global_id
		self._id = _global_id
		_global_id += 1
	
	def __repr__(self):
		return 'GameObject({})'.format(', '.join(['{}={}'.format(k, type(v).__name__ if isinstance(v,Container) else v)
		                                          for k,v in self.__dict__.items()]))
	
	def __str__(self):
		return self.name


