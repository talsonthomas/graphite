#Copyright 2008 Orbitz WorldWide
#
#Licensed under the Apache License, Version 2.0 (the "License");
#you may not use this file except in compliance with the License.
#You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
#Unless required by applicable law or agreed to in writing, software
#distributed under the License is distributed on an "AS IS" BASIS,
#WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#See the License for the specific language governing permissions and
#limitations under the License.

"""
These functions are used on the metrics passed in the ``&target=``
URL parameters to change the data being graphed in some way.
"""

from graphite.render.datalib import TimeSeries, timestamp
from graphite.render.attime import parseTimeOffset
from itertools import izip
import math
import re

#Utility functions
def safeSum(values):
  safeValues = [v for v in values if v is not None]
  if not safeValues: return None
  return sum(safeValues)

def safeDiff(values):
  safeValues = [v for v in values if v is not None]
  if not safeValues: return None
  values = map(lambda x: x*-1, safeValues[1:])
  values.insert(0, safeValues[0])
  return sum(values)

def safeLen(values):
  return len([v for v in values if v is not None])

def safeDiv(a,b):
  if a is None: return None
  if b in (0,None): return None
  return float(a) / float(b)

def safeMul(a,b):
  if a is None or b is None: return None
  return float(a) * float(b)

def safeLast(values):
  for v in reversed(values):
    if v is not None: return v

def safeMin(values):
  safeValues = [v for v in values if v is not None]
  if safeValues:
    return min(safeValues)

def safeMax(values):
  safeValues = [v for v in values if v is not None]
  if safeValues:
    return max(safeValues)

def lcm(a,b):
  if a == b: return a
  if a < b: (a,b) = (b,a) #ensure a > b
  for i in xrange(1,a * b):
    if a % (b * i) == 0 or (b * i) % a == 0: #probably inefficient
      return max(a,b * i)
  return a * b

def normalize(seriesLists):
  seriesList = reduce(lambda L1,L2: L1+L2,seriesLists)
  step = reduce(lcm,[s.step for s in seriesList])
  for s in seriesList:
    s.consolidate( step / s.step )
  start = min([s.start for s in seriesList])
  end = max([s.end for s in seriesList])
  end -= (end - start) % step
  return (seriesList,start,end,step)

# Series Functions

#NOTE: Some of the functions below use izip, which may be problematic.
#izip stops when it hits the end of the shortest series
#in practice this *shouldn't* matter because all series will cover
#the same interval, despite having possibly different steps...

def sumSeries(requestContext, *seriesLists):
  """
  Short form: sum()

  This will add metrics together and return the sum at each datapoint. (See
  integral for a sum over time)

  Example:

  .. code-block:: none

    &target=sum(company.server.application*.requestsHandled)

  This would show the sum of all requests handled per minute (provided
  requestsHandled are collected once a minute).   If metrics with different
  retention rates are combined, the coarsest metric is graphed, and the sum
  of the other metrics is averaged for the metrics with finer retention rates.

  """

  try:
    (seriesList,start,end,step) = normalize(seriesLists)
  except:
    return []
  #name = "sumSeries(%s)" % ','.join((s.name for s in seriesList))
  name = "sumSeries(%s)" % ','.join(set([s.pathExpression for s in seriesList]))
  values = ( safeSum(row) for row in izip(*seriesList) )
  series = TimeSeries(name,start,end,step,values)
  series.pathExpression = name
  return [series]

def sumSeriesWithWildcards(requestContext, seriesList, *position): #XXX
  """
  Call sumSeries after inserting wildcards at the given position(s).

  Example:

  .. code-block:: none

    &target=sumSeriesWithWildcards(host.cpu-[0-7].cpu-{user,system}.value, 1)

  This would be the equivalent of
  ``target=sumSeries(host.*.cpu-user.value)&target=sumSeries(host.*.cpu-system.value)``

  """
  if type(position) is int:
    positions = [position]
  else:
    positions = position

  newSeries = {}
  newNames = list()

  for series in seriesList:
    newname = '.'.join(map(lambda x: x[1], filter(lambda i: i[0] not in positions, enumerate(series.name.split('.')))))
    if newname in newSeries.keys():
      newSeries[newname] = sumSeries(requestContext, (series, newSeries[newname]))[0]
    else:
      newSeries[newname] = series
      newNames.append(newname)
    newSeries[newname].name = newname

  return [newSeries[name] for name in newNames]

def averageSeriesWithWildcards(requestContext, seriesList, *position): #XXX
  if type(position) is int:
    positions = [position]
  else:
    positions = position
  result = []
  matchedList = {}
  for series in seriesList:
    newname = '.'.join(map(lambda x: x[1], filter(lambda i: i[0] not in positions, enumerate(series.name.split('.')))))
    if not matchedList.has_key(newname):
      matchedList[newname] = []
    matchedList[newname].append(series)
  for name in matchedList.keys():
    result.append( averageSeries(requestContext, (matchedList[name]))[0] )
    result[-1].name = name
  return result

def diffSeries(requestContext, *seriesLists):
  """
  Can take two or more metrics, or a single metric and a constant.
  Subtracts parameters 2 through n from parameter 1.

  Example:

  .. code-block:: none

    &target=diffSeries(service.connections.total,service.connections.failed)
    &target=diffSeries(service.connections.total,5)

  """
  (seriesList,start,end,step) = normalize(seriesLists)
  name = "diffSeries(%s)" % ','.join(set([s.pathExpression for s in seriesList]))
  values = ( safeDiff(row) for row in izip(*seriesList) )
  series = TimeSeries(name,start,end,step,values)
  series.pathExpression = name
  return [series]

def averageSeries(requestContext, *seriesLists):
  """
  Short Alias: avg()

  Takes one metric or a wildcard seriesList.
  Draws the average value of all metrics passed at each time.

  Example:

  .. code-block:: none

    &target=averageSeries(company.server.*.threads.busy)

  """
  (seriesList,start,end,step) = normalize(seriesLists)
  #name = "averageSeries(%s)" % ','.join((s.name for s in seriesList))
  name = "averageSeries(%s)" % ','.join(set([s.pathExpression for s in seriesList]))
  values = ( safeDiv(safeSum(row),safeLen(row)) for row in izip(*seriesList) )
  series = TimeSeries(name,start,end,step,values)
  series.pathExpression = name
  return [series]

def minSeries(requestContext, *seriesLists):
  """
  Takes one metric or a wildcard seriesList.
  For each datapoint from each metric passed in, pick the minimum value and graph it.

  Example:

  .. code-block:: none

    &target=minSeries(Server*.connections.total)
  """
  (seriesList, start, end, step) = normalize(seriesLists)
  pathExprs = list( set([s.pathExpression for s in seriesList]) )
  name = "minSeries(%s)" % ','.join(pathExprs)
  values = ( safeMin(row) for row in izip(*seriesList) )
  series = TimeSeries(name, start, end, step, values)
  series.pathExpression = name
  return [series]

def maxSeries(requestContext, *seriesLists):
  """
  Takes one metric or a wildcard seriesList.
  For each datapoint from each metric passed in, pick the maximum value and graph it.

  Example:

  .. code-block:: none

    &target=maxSeries(Server*.connections.total)

  """
  (seriesList, start, end, step) = normalize(seriesLists)
  pathExprs = list( set([s.pathExpression for s in seriesList]) )
  name = "maxSeries(%s)" % ','.join(pathExprs)
  values = ( safeMax(row) for row in izip(*seriesList) )
  series = TimeSeries(name, start, end, step, values)
  series.pathExpression = name
  return [series]

def keepLastValue(requestContext, seriesList):
  """
  Takes one metric or a wildcard seriesList.
  Continues the line with the last received value when gaps ('None' values) appear in your data, rather than breaking your line.

  Example:

  .. code-block:: none

    &target=keepLastValue(Server01.connections.handled)

  """
  for series in seriesList:
    series.name = "keepLastValue(%s)" % (series.name)
    for i,value in enumerate(series):
      if value is None and i != 0:
        value = series[i-1]
      series[i] = value
  return seriesList

def asPercent(requestContext, seriesList1, seriesList2orNumber):
  """
  Takes exactly two metrics, or a metric and a constant.
  Draws the first metric as a percent of the second.

  Example:

  .. code-block:: none

    &target=asPercent(Server01.connections.failed,Server01.connections,total)
    &target=asPercent(apache01.threads.busy,1500)

  """
  assert len(seriesList1) == 1, "asPercent series arguments must reference *exactly* 1 series"
  series1 = seriesList1[0]
  if type(seriesList2orNumber) is list:
    assert len(seriesList2orNumber) == 1, "asPercent series arguments must reference *exactly* 1 series"
    series2 = seriesList2orNumber[0]
    name = "asPercent(%s,%s)" % (series1.name,series2.name)
    series = (series1,series2)
    step = reduce(lcm,[s.step for s in series])
    for s in series:
      s.consolidate( step / s.step )
    start = min([s.start for s in series])
    end = max([s.end for s in series])
    end -= (end - start) % step
    values = ( safeMul( safeDiv(v1,v2), 100.0 ) for v1,v2 in izip(*series) )
  else:
    number = float(seriesList2orNumber)
    name = "asPercent(%s,%.1f)" % (series1.name,number)
    step = series1.step
    start = series1.start
    end = series1.end
    values = ( safeMul( safeDiv(v,number), 100.0 ) for v in series1 )
  series = TimeSeries(name,start,end,step,values)
  series.pathExpression = name
  return [series]


def divideSeries(requestContext, dividendSeriesList, divisorSeriesList):
  """
  Takes a dividend metric and a divisor metric and draws the division result.
  A constant may *not* be passed. To divide by a constant, use the scale() 
  function (which is essentially a multiplication operation) and use the inverse
  of the dividend. (Division by 8 = multiplication by 1/8 or 0.125)

  Example:

  .. code-block:: none

    &target=asPercent(Series.dividends,Series.divisors)


  """
  if len(divisorSeriesList) != 1:
    raise ValueError("divideSeries second argument must reference exactly 1 series")

  divisorSeries = divisorSeriesList[0]
  results = []

  for dividendSeries in dividendSeriesList:
    name = "divideSeries(%s,%s)" % (dividendSeries.name, divisorSeries.name)
    bothSeries = (dividendSeries, divisorSeries)
    step = reduce(lcm,[s.step for s in bothSeries])

    for s in bothSeries:
      s.consolidate( step / s.step )

    start = min([s.start for s in bothSeries])
    end = max([s.end for s in bothSeries])
    end -= (end - start) % step

    values = ( safeDiv(v1,v2) for v1,v2 in izip(*bothSeries) )

    quotientSeries = TimeSeries(name, start, end, step, values)
    quotientSeries.pathExpression = name
    results.append(quotientSeries)

  return results


def scale(requestContext, seriesList, factor):
  """
  Takes one metric or a wildcard seriesList followed by a constant, and multiplies the datapoint
  by the constant provided at each point.

  Example:

  .. code-block:: none

    &target=scale(Server.instance01.threads.busy,10)
    &target=scale(Server.instance*.threads.busy,10)

  """
  for series in seriesList:
    series.name = "scale(%s,%.1f)" % (series.name,float(factor))
    for i,value in enumerate(series):
      series[i] = safeMul(value,factor)
  return seriesList

def offset(requestContext, seriesList, factor):
  """
  Takes one metric or a wildcard seriesList followed by a constant, and adds the constant to
  each datapoint.

  Example:

  .. code-block:: none

    &target=offset(Server.instance01.threads.busy,10)

  """
  for series in seriesList:
    series.name = "offset(%s,%.1f)" % (series.name,float(factor))
    for i,value in enumerate(series):
      if value is not None:
        series[i] = value + factor
  return seriesList

def movingAverage(requestContext, seriesList, windowSize):
  """
  Takes one metric or a wildcard seriesList followed by a number N of datapoints and graphs
  the average of N previous datapoints.  N-1 datapoints are set to None at the
  beginning of the graph.

  .. code-block:: none

    &target=movingAverage(Server.instance01.threads.busy,10)

  """
  for seriesIndex, series in enumerate(seriesList):
    newName = "movingAverage(%s,%.1f)" % (series.name, float(windowSize))
    newSeries = TimeSeries(newName, series.start, series.end, series.step, [])
    newSeries.pathExpression = newName

    windowIndex = windowSize - 1

    for i in range( len(series) ):
      if i < windowIndex: # Pad the beginning with None's since we don't have enough data
        newSeries.append( None )

      else:
        window = series[i - windowIndex : i + 1]
        nonNull = [ v for v in window if v is not None ]
        if nonNull:
          newSeries.append( sum(nonNull) / len(nonNull) )
        else:
          newSeries.append(None)

    seriesList[ seriesIndex ] = newSeries

  return seriesList

def cumulative(requestContext, seriesList):
  """
  Takes one metric or a wildcard seriesList.

  By default, when a graph is drawn, and the width of the graph in pixels is
  smaller than the number of datapoints to be graphed, Graphite averages the 
  value at each pixel.  The cumulative() function changes the consolidation 
  function to sum from average.  This is especially useful in sales graphs, 
  where fractional values make no sense (How can you have half of a sale?)

  .. code-block:: none

    &target=cumulative(Sales.widgets.largeBlue)

  """
  for series in seriesList:
    series.consolidationFunc = 'sum'
    series.name = 'cumulative(%s)' % series.name
  return seriesList

def derivative(requestContext, seriesList):
  """
  This is the opposite of the integral function.  This is useful for taking a
  running total metric and showing how many requests per minute were handled.

  Example:

  .. code-block:: none

    &target=derivative(company.server.application01.ifconfig.TXPackets)

  Each time you run ifconfig, the RX and TXPackets are higher (assuming there
  is network traffic.) By applying the derivative function, you can get an
  idea of the packets per minute sent or received, even though you're only
  recording the total.
  """
  results = []
  for series in seriesList:
    newValues = []
    prev = None
    for val in series:
      if None in (prev,val):
        newValues.append(None)
        prev = val
        continue
      newValues.append(val - prev)
      prev = val
    newName = "derivative(%s)" % series.name
    newSeries = TimeSeries(newName, series.start, series.end, series.step, newValues)
    newSeries.pathExpression = newName
    results.append(newSeries)
  return results

def integral(requestContext, seriesList):
  """
  This will show the sum over time, sort of like a continuous addition function.
  Useful for finding totals or trends in metrics that are collected per minute.

  Example:

  .. code-block:: none

    &target=integral(company.sales.perMinute)

  This would start at zero on the left side of the graph, adding the sales each
  minute, and show the total sales for the time period selected at the right
  side, (time now, or the time specified by '&until=').
  """
  results = []
  for series in seriesList:
    newValues = []
    current = 0.0
    for val in series:
      if val is None:
        newValues.append(None)
      else:
        current += val
        newValues.append(current)
    newName = "integral(%s)" % series.name
    newSeries = TimeSeries(newName, series.start, series.end, series.step, newValues)
    newSeries.pathExpression = newName
    results.append(newSeries)
  return results


def nonNegativeDerivative(requestContext, seriesList, maxValue=None):
  """
  Same as the derivative function above, but ignores datapoints that trend
  down.  Useful for counters that increase for a long time, then wrap or
  reset. (Such as if a network interface is destroyed and recreated by unloading
  and re-loading a kernel module, common with USB / WiFi cards.

  Example:

  .. code-block:: none

    &target=derivative(company.server.application01.ifconfig.TXPackets)

  """
  results = []

  for series in seriesList:
    newValues = []
    prev = None

    for val in series:
      if None in (prev, val):
        newValues.append(None)
        prev = val
        continue

      diff = val - prev
      if diff >= 0:
        newValues.append(diff)
      elif maxValue is not None and maxValue >= val:
        newValues.append( (maxValue - prev) + val  + 1 )
      else:
        newValues.append(None)

      prev = val

    newName = "nonNegativeDerivative(%s)" % series.name
    newSeries = TimeSeries(newName, series.start, series.end, series.step, newValues)
    newSeries.pathExpression = newName
    results.append(newSeries)

  return results


def alias(requestContext, seriesList, newName):
  """
  Takes one metric or a wildcard seriesList and a string in quotes.
  Prints the string instead of the metric name in the legend.

  .. code-block:: none

    &target=alias(Sales.widgets.largeBlue,"Large Blue Widgets")

  """
  for series in seriesList:
    series.name = newName
  return seriesList

def color(requestContext, seriesList, theColor):
  """
  Assigns the given color to the seriesList

  Example:

  .. code-block:: none

    &target=color(collectd.hostname.cpu.0.user, 'green')
    &target=color(collectd.hostname.cpu.0.system, 'ff0000')
    &target=color(collectd.hostname.cpu.0.idle, 'gray')
    &target=color(collectd.hostname.cpu.0.idle, '6464ffaa')

  """
  for series in seriesList:
    series.color = theColor
  return seriesList

def substr(requestContext, seriesList, start=0, stop=0):
  """
  Takes one metric or a wildcard seriesList followed by 1 or 2 integers.  Assume that the
  metric name is a list or array, with each element separated by dots.  Prints
  n - length elements of the array (if only one integer n is passed) or n - m
  elements of the array (if two integers n and m are passed).  The list starts
  with element 0 and ends with element (length - 1).

  Example:

  .. code-block:: none

    &target=substr(carbon.agents.hostname.avgUpdateTime,2,4)

  The label would be printed as "hostname.avgUpdateTime".

  """
  for series in seriesList:
    left = series.name.rfind('(') + 1
    right = series.name.find(')')
    if right < 0:
      right = len(series.name)+1
    cleanName = series.name[left:right:]
    if int(stop) == 0:
      series.name = '.'.join(cleanName.split('.')[int(start)::])
    else:
      series.name = '.'.join(cleanName.split('.')[int(start):int(stop):])
  return seriesList


def log(requestContext, seriesList, base=10):
  """
  Takes one metric or a wildcard seriesList, a base, and draws the y-axis in logarithmic
  format.  If base is omitted, the function defaults to base 10.

  Example:

  .. code-block:: none

    &target=log(carbon.agents.hostname.avgUpdateTime,2)

  """
  results = []
  for series in seriesList:
    newValues = []
    for val in series:
      if val is None:
        newValues.append(None)
      elif val <= 0:
        newValues.append(None)
      else:
        newValues.append(math.log(val, base))
    newName = "log(%s, %s)" % (series.name, base)
    newSeries = TimeSeries(newName, series.start, series.end, series.step, newValues)
    newSeries.pathExpression = newName
    results.append(newSeries)
  return results


def maximumAbove(requestContext, seriesList, n):
  """
  Takes one metric or a wildcard seriesList followed by a constant n.
  Draws only the metrics with a maximum value above n.

  Example:

  .. code-block:: none

    &target=maximumAbove(system.interface.eth*.packetsSent,1000)

  This would only display interfaces which sent more than 1000 packets/min.
  """
  results = []
  for series in seriesList:
    if max(series) >= n:
      results.append(series)
  return results


def maximumBelow(requestContext, seriesList, n):
  """
  Takes one metric or a wildcard seriesList followed by a constant n.
  Draws only the metrics with a maximum value below n.

  Example:

  .. code-block:: none

    &target=maximumBelow(system.interface.eth*.packetsSent,1000)

  This would only display interfaces which sent less than 1000 packets/min.
  """

  result = []
  for series in seriesList:
    if max(series) <= n:
      result.append(series)
  return result


def highestCurrent(requestContext, seriesList, n):
  """
  Takes one metric or a wildcard seriesList followed by an integer N.
  Out of all metrics passed, draws only the N metrics with the highest value
  at the end of the time period specified.

  Example:

  .. code-block:: none

    &target=highestCurrent(server*.instance*.threads.busy,5)

  Draws the 5 servers with the highest busy threads.

  """
  return sorted( seriesList, key=safeLast )[-n:]

def highestMax(requestContext, seriesList, n):
  """
  Takes one metric or a wildcard seriesList followed by an integer N.

  Out of all metrics passed, draws only the N metrics with the highest maximum
  value in the time period specified.

  Example:

  .. code-block:: none

    &target=highestCurrent(server*.instance*.threads.busy,5)

  Draws the top 5 servers who have had the most busy threads during the time 
  period specified.

  """
  result_list = sorted( seriesList, key=lambda s: max(s) )[-n:]

  return sorted(result_list, key=lambda s: max(s), reverse=True)

def lowestCurrent(requestContext, seriesList, n):
  """
  Takes one metric or a wildcard seriesList followed by an integer N.
  Out of all metrics passed, draws only the N metrics with the lowest value at
  the end of the time period specified. 

  Example:

  .. code-block:: none

    &target=lowestCurrent(server*.instance*.threads.busy,5)

  Draws the 5 servers with the least busy threads right now.

  """

  return sorted( seriesList, key=safeLast )[:n]

def currentAbove(requestContext, seriesList, n):
  """
  Takes one metric or a wildcard seriesList followed by an integer N.
  Out of all metrics passed, draws only the  metrics whose value is above N
  at the end of the time period specified.

  Example:

  .. code-block:: none

    &target=highestAbove(server*.instance*.threads.busy,50)

  Draws the servers with more than 50 busy threads.

  """
  return [ series for series in seriesList if safeLast(series) >= n ]

def currentBelow(requestContext, seriesList, n):
  """
  Takes one metric or a wildcard seriesList followed by an integer N.
  Out of all metrics passed, draws only the  metrics whose value is below N
  at the end of the time period specified.

  Example:

  .. code-block:: none

    &target=currentBelow(server*.instance*.threads.busy,3)

  Draws the servers with less than 3 busy threads.

  """
  return [ series for series in seriesList if safeLast(series) <= n ]

def highestAverage(requestContext, seriesList, n):
  """
  Takes one metric or a wildcard seriesList followed by an integer N.
  Out of all metrics passed, draws only the top N metrics with the highest
  average value for the time period specified.

  Example:

  .. code-block:: none

    &target=highestAverage(server*.instance*.threads.busy,5)

  Draws the top 5 servers with the highest average value.

  """

  return sorted( seriesList, key=lambda s: safeDiv(safeSum(s),safeLen(s)) )[-n:]

def lowestAverage(requestContext, seriesList, n):
  """
  Takes one metric or a wildcard seriesList followed by an integer N.
  Out of all metrics passed, draws only the bottom N metrics with the lowest
  average value for the time period specified.

  Example:

  .. code-block:: none

    &target=lowestAverage(server*.instance*.threads.busy,5)

  Draws the bottom 5 servers with the lowest average value.

  """

  return sorted( seriesList, key=lambda s: safeDiv(safeSum(s),safeLen(s)) )[:n]

def averageAbove(requestContext, seriesList, n):
  """
  Takes one metric or a wildcard seriesList followed by an integer N.
  Out of all metrics passed, draws only the metrics with an average value
  above N for the time period specified.

  Example:

  .. code-block:: none

    &target=averageAbove(server*.instance*.threads.busy,25)

  Draws the servers with average values above 25.

  """
  return [ series for series in seriesList if safeDiv(safeSum(series),safeLen(series)) >= n ]

def averageBelow(requestContext, seriesList, n):
  """
  Takes one metric or a wildcard seriesList followed by an integer N.
  Out of all metrics passed, draws only the metrics with an average value
  below N for the time period specified.

  Example:

  .. code-block:: none

    &target=averageBelow(server*.instance*.threads.busy,25)

  Draws the servers with average values below 25.

  """
  return [ series for series in seriesList if safeDiv(safeSum(series),safeLen(series)) <= n ]

def percentileOrdinal(n, series):
  result = int( safeDiv(n * len(series), 100) + 0.5 )
  return result

def nPercentile(requestContext, seriesList, n):
  """Returns n-percent of each series in the seriesList."""
  assert n, 'The requested percent is required to be greater than 0'

  results = []
  for s in seriesList:
    # Create a sorted copy of the TimeSeries excluding None values in the values list.
    s_copy = TimeSeries( s.name, s.start, s.end, s.step, sorted( [item for item in s if item is not None] ) )
    if not s_copy:
      continue  # Skip this series because it is empty.

    pord = percentileOrdinal( n, s_copy )
    if pord > 0:
      i = pord - 1
    else:
      i = pord

    perc_val = s_copy[i]
    if perc_val:
      results.append( TimeSeries( '%dth Percentile(%s, %.1f)' % ( n, s_copy.name, perc_val ),
                                  s_copy.start, s_copy.end, s_copy.step, [perc_val] ) )
  return results

def limit(requestContext, seriesList, n):
  """
  Takes one metric or a wildcard seriesList followed by an integer N.

  Only draw the first N metrics.  Useful when testing a wildcard in a metric.

  Example:

  .. code-block:: none

    &target=limit(server*.instance*.memory.free,5)

  Draws only the first 5 instance's memory free.

  """
  return seriesList[0:n]

def sortByMaxima(requestContext, seriesList):
  """
  Takes one metric or a wildcard seriesList.

  Sorts the list of metrics by the maximum value across the time period
  specified.  Useful with the &areaMode=all parameter, to keep the
  lowest value lines visible.

  Example:

  .. code-block:: none

    &target=sortByMaxima(server*.instance*.memory.free)

  """
  def compare(x,y):
    return cmp(max(y), max(x))
  seriesList.sort(compare)
  return seriesList

def sortByMinima(requestContext, seriesList):
  """
  Takes one metric or a wildcard seriesList.

  Sorts the list of metrics by the lowest value across the time period
  specified.

  Example:

  .. code-block:: none

    &target=sortByMinima(server*.instance*.memory.free)

  """
  def compare(x,y):
    return cmp(min(x), min(y))
  newSeries = [series for series in seriesList if max(series) > 0]
  newSeries.sort(compare)
  return newSeries

def mostDeviant(requestContext, n, seriesList):
  """
  Takes an integer N followed by one metric or a wildcard seriesList.
  Draws the N most deviant metrics.
  To find the deviant, the average across all metrics passed is determined,
  and then the average of each metric is compared to the overall average.

    Example:

  .. code-block:: none

    &target=mostDeviant(5, server*.instance*.memory.free)

  Draws the 5 instances furthest from the average memory free.

  """

  deviants = []
  for series in seriesList:
    mean = safeDiv( safeSum(series), safeLen(series) )
    if mean is None: continue
    square_sum = sum([ (value - mean) ** 2 for value in series if value is not None ])
    sigma = safeDiv(square_sum, safeLen(series))
    if sigma is None: continue
    deviants.append( (sigma, series) )
  deviants.sort(key=lambda i: i[0], reverse=True) #sort by sigma
  return [ series for (sigma,series) in deviants ][:n] #return the n most deviant series


# returns a two-element tuple
# the first element is the std dev, the second is the new sum of squares
def doStdDev(sumOfSquares, first, new, n, avg):
   newSumOfSquares = sumOfSquares - (first * first) + (new * new)
   return (math.sqrt((newSumOfSquares / float(n)) - (avg * avg)), newSumOfSquares)


def stdev(requestContext, seriesList, time):
  """
  Takes one metric or a wildcard seriesList followed by an integer N.
  Draw the Standard Deviation of all metrics passed for the past N datapoints. 

  Example:

  .. code-block:: none

    &target=stddev(server*.instance*.threads.busy,30)

  """

  count = 0
  for series in seriesList:
    stddevs = TimeSeries("stddev(%s,%.1f)" % (series.name, float(time)), series.start, series.end, series.step, [])
    stddevs.pathExpression = "stddev(%s,%.1f)" % (series.name, float(time))
    avg = safeDiv(safeSum(series[:time]), time)

    if avg is not None:
      sumOfSquares = sum(map(lambda(x): x * x, [v for v in series[:time] if v is not None]))
      (sd, sumOfSquares) = doStdDev(sumOfSquares, 0, 0, time, avg)
      stddevs.append(sd)
    else:
      stddevs.append(None)

    for (index, el) in enumerate(series[time:]):
      if el is None:
        continue

      toDrop = series[index]
      if toDrop is None:
        toDrop = 0

      s = safeSum([safeMul(time, avg), el, -toDrop])
      avg = safeDiv(s, time)

      if avg is not None:
        (sd, sumOfSquares) = doStdDev(sumOfSquares, toDrop, series[index+time], time, avg)
        stddevs.append(sd)
      else:
        stddevs.append(None)

    for i in range(0, time-1):
      stddevs.insert(0, None)

    seriesList[count] = stddevs
    count = count + 1

  return seriesList

def secondYAxis(requestContext, seriesList):
  """
  Graph the metric on the secondary Y axis.
  """
  for series in seriesList:
    series.options['secondYAxis'] = True
    series.name= 'secondYAxis(%s)' % series.name
  return seriesList

def drawAsInfinite(requestContext, seriesList):
  """
  Takes one metric or a wildcard seriesList.
  If the value is zero, draw the line at 0.  If the value is above zero, draw
  the line at infinity. If the value is null or less than zero, do not draw
  the line.

  Useful for displaying on/off metrics, such as exit codes. (0 = success,
  anything else = failure.)

  Example:

  .. code-block:: none

    drawAsInfinite(Testing.script.exitCode)

  """
  for series in seriesList:
    series.options['drawAsInfinite'] = True
    series.name = 'drawAsInfinite(%s)' % series.name
  return seriesList

def secondYAxis(requestContext, seriesList):
  for series in seriesList:
    series.options['secondYAxis'] = True
    series.name = 'secondYAxis(%s)' % series.name
  return seriesList

def lineWidth(requestContext, seriesList, width):
  """
  Takes one metric or a wildcard seriesList, followed by a float F.

  Draw the selected metrics with a line width of F, overriding the default
  value of 1, or the &lineWidth=X.X parameter.

  Useful for highlighting a single metric out of many, or having multiple 
  line widths in one graph.

  Example:

  .. code-block:: none

    &target=lineWidth(server01.instance01.memory.free,5)

  """
  for series in seriesList:
    series.options['lineWidth'] = width
  return seriesList

def dashed(requestContext, *seriesList):
  """
  Takes one metric or a wildcard seriesList, followed by a float F.

  Draw the selected metrics with a dotted line with segments of length F
  If omitted, the default length of the segments is 5.0

  Example:

  .. code-block:: none

    &target=dashed(server01.instance01.memory.free,2.5)

  """

  if len(seriesList) == 2:
    dashLength = seriesList[1]
  else:
    dashLength = 5
  for series in seriesList[0]:
    series.name = 'dashed(%s, %d)' % (series.name, dashLength)
    series.options['dashed'] = dashLength
  return seriesList[0]


def timeShift(requestContext, seriesList, timeShift):
  """
  Takes one metric or a wildcard seriesList, followed by a length of time, 
  surrounded by double quotes. (See the URL API for examples of time formats.)

  Draw the selected metrics shifted back in time.

  Useful for comparing a metric against itself.

  Example:

  .. code-block:: none

    &target=timeShift(Sales.widgets.largeBlue,"7d")

  """
  delta = abs( parseTimeOffset(timeShift) )
  myContext = requestContext.copy()
  myContext['startTime'] = requestContext['startTime'] - delta
  myContext['endTime'] = requestContext['endTime'] - delta
  series = seriesList[0] # if len(seriesList) > 1, they will all have the same pathExpression, which is all we care about.
  results = []

  for shiftedSeries in evaluateTarget(myContext, series.pathExpression):
    shiftedSeries.name = 'timeShift(%s, %s)' % (shiftedSeries.name, timeShift)
    shiftedSeries.start = series.start
    shiftedSeries.end = series.end
    results.append(shiftedSeries)

  return results


def constantLine(requestContext, value):
  """
  Takes a float F.

  Draws a horizontal line at value F across the graph.

  Example:

  .. code-block:: none

    &target=contstantLine(123.456)

  """
  start = timestamp( requestContext['startTime'] )
  end = timestamp( requestContext['endTime'] )
  step = end - start
  series = TimeSeries(str(value), start, end, step, [value])
  return [series]


def threshold(requestContext, value, label=None, color=None):
  """
  Takes a float F, followed by a label (in double quotes) and a color.
  (See URL API for valid color names & formats.)

  Draws a horizontal line at value F across the graph.

  Example:

  .. code-block:: none

    &target=threshold(123.456, "omgwtfbbq", red)

  """

  series = constantLine(requestContext, value)[0]
  if label:
    series.name = label
  if color:
    series.color = color

  return [series]


def group(requestContext, *seriesLists):
  seriesGroup = []
  for s in seriesLists:
    seriesGroup.extend(s)

  return seriesGroup


def exclude(requestContext, seriesList, pattern):
  """
  Takes a metric or a wildcard seriesList, followed by a regular expression
  in double quotes.  Excludes metrics that match the regular expression. 

  Example:

  .. code-block:: none

    &target=exclude(servers*.instance*.threads.busy,"server02")
  """
  regex = re.compile(pattern)
  return [s for s in seriesList if not regex.search(s.name)]


def summarize(requestContext, seriesList, intervalString):
  """
  Summarize the data into interval buckets of a certain size.

  Example:

  .. code-block:: none

    &target=summarize(counter.errors, "1hour") # errors per hour
    &target=summarize(nonNegativeDerivative(gauge.num_users), "1week") # new users per week
  """
  results = []
  delta = parseTimeOffset(intervalString)
  interval = delta.seconds + (delta.days * 86400)

  for series in seriesList:
    buckets = {}

    timestamps = range( int(series.start), int(series.end), int(series.step) )
    datapoints = zip(timestamps, series)

    for (timestamp, value) in datapoints:
      bucketInterval = int((timestamp - series.start) / interval)

      if bucketInterval not in buckets:
        buckets[bucketInterval] = []

      if value is not None:
        buckets[bucketInterval].append(value)

    newStart = series.start
    newEnd = series.end
    newValues = []
    for timestamp in range( int(series.start), int(series.end), interval ):
      newEnd = timestamp
      bucketInterval = int((timestamp - series.start) / interval)
      bucket = buckets.get(bucketInterval, [])

      if bucket:
        newValues.append( sum(bucket) )
      else:
        newValues.append( None )

    newName = "summarize(%s, \"%s\")" % (series.name, intervalString)
    newSeries = TimeSeries(newName, newStart, newEnd + interval, interval, newValues)
    newSeries.pathExpression = newName
    results.append(newSeries)

  return results


def hitcount(requestContext, seriesList, intervalString):
  """
  Estimate hit counts from a list of time series.

  This function assumes the values in each time series represent
  hits per second.  It calculates hits per some larger interval
  such as per day or per hour.  This function is like summarize(),
  except that it compensates automatically for different time scales
  (so that a similar graph results from using either fine-grained
  or coarse-grained records) and handles rarely-occurring events
  gracefully.
  """
  results = []
  delta = parseTimeOffset(intervalString)
  interval = int(delta.seconds + (delta.days * 86400))

  for series in seriesList:
    length = len(series)
    step = int(series.step)
    bucket_count = int(math.ceil(float(series.end - series.start) / interval))
    buckets = [[] for _ in range(bucket_count)]
    newStart = int(series.end - bucket_count * interval)

    for i, value in enumerate(series):
      if value is None:
        continue

      start_time = int(series.start + i * step)
      start_bucket, start_mod = divmod(start_time - newStart, interval)
      end_time = start_time + step
      end_bucket, end_mod = divmod(end_time - newStart, interval)

      if end_bucket >= bucket_count:
        end_bucket = bucket_count - 1
        end_mod = interval

      if start_bucket == end_bucket:
        # All of the hits go to a single bucket.
        if start_bucket >= 0:
          buckets[start_bucket].append(value * (end_mod - start_mod))

      else:
        # Spread the hits among 2 or more buckets.
        if start_bucket >= 0:
          buckets[start_bucket].append(value * (interval - start_mod))
        hits_per_bucket = value * interval
        for j in range(start_bucket + 1, end_bucket):
          buckets[j].append(hits_per_bucket)
        if end_mod > 0:
          buckets[end_bucket].append(value * end_mod)

    newValues = []
    for bucket in buckets:
      if bucket:
        newValues.append( sum(bucket) )
      else:
        newValues.append(None)

    newName = 'hitcount(%s, "%s")' % (series.name, intervalString)
    newSeries = TimeSeries(newName, newStart, series.end, interval, newValues)
    newSeries.pathExpression = newName
    results.append(newSeries)

  return results


def pieAverage(requestContext, series):
  return safeDiv(safeSum(series),safeLen(series))

def pieMaximum(requestContext, series):
  return max(series)

def pieMinimum(requestContext, series):
  return min(series)

PieFunctions = {
  'average' : pieAverage,
  'maximum' : pieMaximum,
  'minimum' : pieMinimum,
}

SeriesFunctions = {
  # Combine functions
  'sumSeries' : sumSeries,
  'sum' : sumSeries,
  'diffSeries' : diffSeries,
  'divideSeries' : divideSeries,
  'averageSeries' : averageSeries,
  'avg' : averageSeries,
  'sumSeriesWithWildcards': sumSeriesWithWildcards,
  'averageSeriesWithWildcards': averageSeriesWithWildcards,
  'minSeries' : minSeries,
  'maxSeries' : maxSeries,

  # Transform functions
  'scale' : scale,
  'offset' : offset,
  'derivative' : derivative,
  'integral' : integral,
  'nonNegativeDerivative' : nonNegativeDerivative,
  'log' : log,
  'timeShift': timeShift,
  'summarize' : summarize,
  'hitcount'  : hitcount,

  # Calculate functions
  'movingAverage' : movingAverage,
  'stdev' : stdev,
  'asPercent' : asPercent,
  'pct' : asPercent,

  # Filter functions
  'mostDeviant' : mostDeviant,
  'highestCurrent' : highestCurrent,
  'lowestCurrent' : lowestCurrent,
  'highestMax' : highestMax,
  'currentAbove' : currentAbove,
  'currentBelow' : currentBelow,
  'highestAverage' : highestAverage,
  'lowestAverage' : lowestAverage,
  'averageAbove' : averageAbove,
  'averageBelow' : averageBelow,
  'maximumAbove' : maximumAbove,
  'maximumBelow' : maximumBelow,
  'nPercentile' : nPercentile,
  'limit' : limit,
  'sortByMaxima' : sortByMaxima,
  'sortByMinima' : sortByMinima,

  # Special functions
  'alias' : alias,
  'color' : color,
  'cumulative' : cumulative,
  'keepLastValue' : keepLastValue,
  'drawAsInfinite' : drawAsInfinite,
  'secondYAxis': secondYAxis,
  'lineWidth' : lineWidth,
  'dashed' : dashed,
  'substr' : substr,
  'group' : group,
  'exclude' : exclude,
  'constantLine' : constantLine,
  'threshold' : threshold,
}


#Avoid import circularity
from graphite.render.evaluator import evaluateTarget
