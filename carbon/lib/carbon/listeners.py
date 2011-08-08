from twisted.internet import reactor
from twisted.internet.protocol import Factory, DatagramProtocol
from twisted.internet.error import ConnectionDone
from twisted.protocols.basic import LineOnlyReceiver, Int32StringReceiver
from carbon.cache import MetricCache
from carbon.events import metricReceived
from carbon.util import LoggingMixin
from carbon import log

try:
  import cPickle as pickle
except ImportError:
  import pickle


class LoggingMixin:
  def connectionMade(self):
    self.peer = self.transport.getPeer()
    self.peerAddr = "%s:%d" % (self.peer.host, self.peer.port)
    log.listener("%s connection with %s established" % (self.__class__.__name__, self.peerAddr))

  def connectionLost(self, reason):
    if reason.check(ConnectionDone):
      log.listener("%s connection with %s closed cleanly" % (self.__class__.__name__, self.peerAddr))
    else:
      log.listener("%s connection with %s lost: %s" % (self.__class__.__name__, self.peerAddr, reason.value))
    self.factory.clientDisconnected(self)


class MetricLineReceiver(LoggingMixin, LineOnlyReceiver):
  delimiter = '\n'

  def lineReceived(self, line):
    try:
      metric, value, timestamp = line.strip().split()
      datapoint = ( float(timestamp), float(value) )
    except:
      log.listener('invalid line received from client %s, ignoring' % self.peerAddr)
      return

    increment('metricsReceived')
    metricReceived(metric, datapoint)


class MetricDatagramReceiver(LoggingMixin, DatagramProtocol):
  def datagramReceived(self, data, (host, port)):
    for line in data.splitlines():
      try:
        metric, value, timestamp = line.strip().split()
        datapoint = ( float(timestamp), float(value) )

        increment('metricsReceived')
        metricReceived(metric, datapoint)
      except:
        log.listener('invalid line received from client %s, ignoring' % host)


class MetricPickleReceiver(LoggingMixin, Int32StringReceiver):
  MAX_LENGTH = 2 ** 20

  def stringReceived(self, data):
    try:
      datapoints = pickle.loads(data)
    except:
      log.listener('invalid pickle received from client %s, ignoring' % self.peerAddr)
      return

    for (metric, datapoint) in datapoints:
      try:
        datapoint = ( float(datapoint[0]), float(datapoint[1]) ) #force proper types
      except:
        continue

      if datapoint[1] == datapoint[1]: # filter out NaN values
        metricReceived(metric, datapoint)

    increment('metricsReceived', len(datapoints))



class CacheQueryHandler(LoggingMixin, Int32StringReceiver):
  def stringReceived(self, metric):
    values = MetricCache.get(metric, [])
    log.query('cache query for %s returned %d values' % (metric, len(values)))
    response = pickle.dumps(values, protocol=-1)
    self.sendString(response)
    increment('cacheQueries')


class ReceiverFactory(Factory):
  def startFactory(self):
    self.clients = []

  def buildProtocol(self, addr):
    p = self.protocol()
    p.factory = self
    self.clients.append(p)

  def clientDisconnected(self, client):
    if client in self.clients:
      self.clients.remove(client)


class ClientManager:
  def __init__(self):
    self.factories = []
    self.clientsPaused = False

  def createFactory(self, protocol):
    factory = ReceiverFactory()
    factory.protocol = protocol
    self.factories.append(factory)
    return factory

  @property
  def clients(self):
    for factory in self.factories:
      for client in factory.clients:
        yield client

  def pauseAllClients(self):
    log.listener("ClientManager.pauseAllClients")
    for client in self.clients:
      client.transport.pauseProducing()
    self.clientsPaused = True

  def resumeAllClients(self):
    log.listener("ClientManager.resumeAllClients")
    for client in self.clients:
      client.transport.resumeProducing()
    self.clientsPaused = False


ClientManager = ClientManager() # ghetto singleton


def startListener(interface, port, protocol):
  factory = ClientManager.createFactory(protocol)
  return reactor.listenTCP( int(port), factory, interface=interface )

# Avoid import circularity
from carbon.instrumentation import increment
