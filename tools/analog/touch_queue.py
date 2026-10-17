"""Retain short touch edges across ACK waits; continuous positions stay current."""
from collections import deque

class TouchQueue:
    MAX_AGE=.250
    MIN_HOLD=.035
    MAX_EDGES=32

    def __init__(self):
        self.latest={};self.edges=deque();self.sent={};self.down_at={}
        self.active=True;self.expired=0
        self.release_barrier=False

    def offer(self,points,now,active=True):
        if not active:
            if self.active or self.latest or self.sent:self.release_barrier=True
            self.active=False;self.latest={};self.edges.clear()
            return
        self.active=True
        snapshot=dict(points)
        if set(snapshot)!=set(self.latest):
            if len(self.edges)>=self.MAX_EDGES:
                self.edges.popleft();self.expired+=1
            self.edges.append((now,snapshot))
        self.latest=snapshot

    def take(self,now):
        if not self.active or self.release_barrier:return {}
        while self.edges and now-self.edges[0][0]>self.MAX_AGE:
            self.edges.popleft();self.expired+=1
        candidate=self.edges[0][1] if self.edges else self.latest
        # A queued DOWN and UP may both be ready when an earlier ACK arrives.
        # Give the game a visible press, rather than injecting both in one instant.
        released=set(self.sent)-set(candidate)
        if any(ident>=3 and now-self.down_at.get(ident,now)<self.MIN_HOLD for ident in released):
            return self.continuous(self.sent)
        if self.edges:self.edges.popleft()
        return self.continuous(candidate)

    def continuous(self,snapshot):
        result=dict(snapshot)
        for ident in (1,2):
            if ident in result and ident in self.sent and ident in self.latest:
                result[ident]=self.latest[ident]
        return result

    def mark_sent(self,points,now):
        self.down_at={ident:self.down_at.get(ident,now) for ident in points}
        self.sent=dict(points)
        if not points:self.release_barrier=False
