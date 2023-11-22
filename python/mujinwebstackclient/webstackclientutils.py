from functools import wraps
import copy

maxQueryLimit = 100

class QueryIterator:
    """Converts a large query to a iterator. The iterator will internally query webstack with a few small queries
    example:

      iterator = QueryIterator(client.GetScenes)
      iterator = QueryIterator(client.GetScenes, offset=10, limit=10)
      for scene in QueryIterator(client.GetScenes, offset=10, limit=10):
          do_something(scene)
    """

    _queryFunction = None # the actual webstack client query function (e.g. client.GetScenes)
    _args = None # positional arguments supplied to the query function (e.g. scenepk)
    _kwargs = None # keyword arguments supplied to the query function (e.g. offset=10, limit=20)
    _items = None # internal buffer for items retrieved from webstack
    _shouldStop = None # boolean flag indicates whether need to query webstack again
    _totalLimit = None # the number of items user requests (0 means no limit)
    _count = None # the number of items already returned to user
    _totalCount = None # the number of items available on webstack

    def __init__(self, queryFunction, *args, **kwargs):
        """Initialize all internal variables
        """
        if hasattr(queryFunction, "inner"):
            args = (queryFunction.__self__,) + args
            queryFunction = queryFunction.inner
        self._queryFunction = queryFunction
        self._args = args
        self._kwargs = copy.deepcopy(kwargs)
        self._items = []
        self._shouldStop = False
        self._kwargs.setdefault('offset', 0)
        self._kwargs.setdefault('limit', 0)
        self._totalLimit = self._kwargs['limit']
        self._count = 0
        if self._kwargs['limit'] > 0:
            self._kwargs['limit'] = min(self._kwargs['limit'], maxQueryLimit)
        else:
            self._kwargs['limit'] = maxQueryLimit

    def __iter__(self):
        return self
    
    def __next__(self):
        """Retrieve the next item from iterator
           Required by Python3
        """
        return self.next()

    def next(self):
        """Retrieve the next item from iterator
           Required by Python2
        """
        # return an item from internal buffer if buffer is not empty
        if len(self._items) != 0:
            item = self._items[0]
            self._items = self._items[1:]
            self._count += 1
            return item

        # stop iteration if internal buffer is empty and no need to query webstack again
        if self._shouldStop:
            raise StopIteration

        # query webstack if buffer is empty
        self._items = self._queryFunction(*self._args, **self._kwargs)
        self._totalCount = self._items.totalCount
        self._kwargs['offset'] += len(self._items)

        if len(self._items) < self._kwargs['limit']:
            # webstack does not have more items
            self._shouldStop = True
        if self._totalLimit != 0 and self._count + len(self._items) >= self._totalLimit:
            # all remaining items user requests are in internal buffer, no need to query webstack again
            self._shouldStop = True
            self._items = self._items[:self._totalLimit - self._count]

        return self.next()

class QueryResult(list):
    """Wraps query response. Break large query into small queries automatically to save memory.
    """
    _queryFunction = None # the actual webstack client query function (e.g. client.GetScenes)
    _args = None # positional arguments supplied to the query function (e.g. scenepk)
    _kwargs = None # keyword arguments supplied to the query function (e.g. offset=10, limit=20)
    _meta = None  # meta dict returned from server
    _items = None # internal buffer for items retrieved from webstack
    _limit = None # query limit specified by the user
    _offset = None # query offset specified by the user
    _currentOffset = None # the offset for the first value inside buffer
    _fetchedAll = None # whether already has a complete list of query result

    def __init__(self, queryFunction, *args, **kwargs):
        self._queryFunction = queryFunction
        self._args = args
        self._kwargs = copy.deepcopy(kwargs)
        self._kwargs.setdefault('offset', 0)
        self._kwargs.setdefault('limit', 0)
        self._limit = self._kwargs['limit']
        self._offset = self._kwargs['offset']
        self._APICall(offset=self._offset)
        self._fetchedAll = False

    def __iter__(self):
        if self._fetchedAll:
            return super(QueryResult, self).__iter__()
        self._kwargs['offset'] = self._offset
        self._kwargs['limit'] = self._limit
        return QueryIterator(self._queryFunction, *self._args, **self._kwargs)
    
    def _APICall(self, offset):
        """make one webstack query
        """
        self._kwargs['offset'] = offset
        self._kwargs['limit'] = maxQueryLimit
        self._items = self._queryFunction(*self._args, **self._kwargs)
        self._meta = self._items._meta
        self._currentOffset = offset

    @property
    def totalCount(self):
        return self._meta['total_count']

    @property
    def limit(self):
        return self._meta['limit']

    @property
    def offset(self):
        return self._meta['offset']
    
    def FetchAll(self):
        """fetch the complete query result from webstack
        """
        if self._fetchedAll:
            return
        self._kwargs['offset'] = self._offset
        self._kwargs['limit'] = self._limit
        items = [item for item in QueryIterator(self._queryFunction, *self._args, **self._kwargs)]
        super(QueryResult, self).__init__(items)
        self._fetchedAll = True

    def __len__(self):
        if self._fetchedAll:
            return super(QueryResult, self).__len__()
        if self._limit == 0 or self._offset + self._limit >= self.totalCount:
            return max(0, self.totalCount - self._offset)
        return self._limit

    def __getitem__(self, index):
        if self._fetchedAll:
            return super(QueryResult, self).__getitem__(index)
        
        if index < 0:
            index = len(self) + index

        if index >= len(self):
            raise IndexError('query result index out of range')

        offset = self._offset + index
        if offset >= self._currentOffset and offset < self._currentOffset + maxQueryLimit:
            # buffer hit
            return self._items[offset - self._currentOffset]
        
        # drop buffer and query webstack again
        self._APICall(offset=offset)
        return self.__getitem__(index)

    def __repr__(self):
        if self._fetchedAll:
            return super(QueryResult, self).__repr__()
        return "<Query result object>"

    # When invoke the following functions, 
    # QueryResult object will fetch the complete list of query result from webstack,
    # and it behaves identical to a standard list from this point forward.

    def __setitem__(self, index, item):
        self.FetchAll()
        return super(QueryResult, self).__setitem__(index, item)

    def append(self, item):
        self.FetchAll()
        return super(QueryResult, self).append(item)

    def extend(self, items):
        self.FetchAll()
        return super(QueryResult, self).extend(items)

    def insert(self, index, item):
        self.FetchAll()
        return super(QueryResult, self).insert(index, item)

    def index(self, item, start=0, end=None):
        self.FetchAll()
        if end is None:
            end = len(self)
        return super(QueryResult, self).index(item, start, end)

    def pop(self):
        self.FetchAll()
        return super(QueryResult, self).pop()

    def count(self, item):
        self.FetchAll()
        return super(QueryResult, self).count(item)

    def remove(self, item):
        self.FetchAll()
        return super(QueryResult, self).remove(item)

    def reverse(self):
        self.FetchAll()
        return super(QueryResult, self).reverse()

    def sort(self, reverse=False, key=None):
        self.FetchAll()
        return super(QueryResult, self).sort(reverse=reverse, key=key)

    def __iadd__(self, items):
        self.FetchAll()
        return super(QueryResult, self).__iadd__(items)

    def __add__(self, items):
        self.FetchAll()
        return super(QueryResult, self).__add__(items)

    def __rmul__(self, value):
        self.FetchAll()
        return super(QueryResult, self).__rmul__(value)

    def __mul__(self, value):
        self.FetchAll()
        return super(QueryResult, self).__mul__(value)

    def __imul__(self, value):
        self.FetchAll()
        return super(QueryResult, self).__imul__(value)

    def __reversed__(self):
        self.FetchAll()
        return super(QueryResult, self).__reversed__()

    def __contains__(self, item):
        self.FetchAll()
        return super(QueryResult, self).__contains__(item)

    def __delitem__(self, index):
        self.FetchAll()
        return super(QueryResult, self).__delitem__(index)
    
    def __eq__(self, other):
        self.FetchAll()
        if isinstance(other, QueryResult):
            other.FetchAll()
        return super(QueryResult, self).__eq__(other)
    
    def __ne__(self, other):
        self.FetchAll()
        if isinstance(other, QueryResult):
            other.FetchAll()
        return super(QueryResult, self).__ne__(other)
    
    def __lt__(self, other):
        self.FetchAll()
        if isinstance(other, QueryResult):
            other.FetchAll()
        return super(QueryResult, self).__lt__(other)
    
    def __gt__(self, other):
        self.FetchAll()
        if isinstance(other, QueryResult):
            other.FetchAll()
        return super(QueryResult, self).__gt__(other)
    
    def __le__(self, other):
        self.FetchAll()
        if isinstance(other, QueryResult):
            other.FetchAll()
        return super(QueryResult, self).__le__(other)
    
    def __ge__(self, other):
        self.FetchAll()
        if isinstance(other, QueryResult):
            other.FetchAll()
        return super(QueryResult, self).__ge__(other)

def UseQueryResult(queryFunction):
    """This decorator break a large query into a few small queries with the help of QueryResult class to prevent webstack from consuming too much memory.
    """
    @wraps(queryFunction)
    def wrapper(self, *args, **kwargs):
        queryResult = QueryResult(queryFunction, *((self,) + args), **kwargs)
        return queryResult
    
    wrapper.inner = queryFunction
    return wrapper    
