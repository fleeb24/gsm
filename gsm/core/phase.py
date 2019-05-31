from ..signals import PhaseComplete

class GamePhase(object):
	
	def __init__(self, name=None):
		
		if name is None:
			name = type(self).__name__
		self.name = name
	
	def execute(self, G, player=None, action=None): # must be implemented
		raise NotImplementedError
	
	def encode(self, G): # by default no actions are necessary
		raise PhaseComplete


class EndPhase(GamePhase):
	pass