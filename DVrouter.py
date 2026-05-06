####################################################
# DVrouter.py
#####################################################

from router import Router
from packet import Packet
import json

INF = 16


class DVrouter(Router):

    def __init__(self, addr, heartbeat_time):
        Router.__init__(self, addr)
        self.heartbeat_time = heartbeat_time
        self.last_time = 0
        self.neighbors = {}
        self.distance_vector = {self.addr: 0}
        self.forwarding_table = {}
        self.neighbor_dvs = {}

    def send_dv(self, port):
        pkt = Packet(Packet.ROUTING, self.addr, None)
        pkt.content = json.dumps(self.distance_vector)
        self.send(port, pkt)

    def broadcast_dv(self):
        for port in self.neighbors:
            self.send_dv(port)

    def recompute(self):
        all_dests = set()
        for port, (nbr, cost) in self.neighbors.items():
            all_dests.add(nbr)
        for nbr_dv in self.neighbor_dvs.values():
            all_dests.update(nbr_dv.keys())
        all_dests.discard(self.addr)

        new_dv = {self.addr: 0}
        new_ft = {}

        for dest in all_dests:
            best_cost = INF
            best_port = None

            for port, (nbr, link_cost) in self.neighbors.items():
                if dest == nbr:
                    candidate = link_cost
                elif nbr in self.neighbor_dvs:
                    candidate = link_cost + self.neighbor_dvs[nbr].get(dest, INF)
                else:
                    candidate = INF

                candidate = min(candidate, INF)

                if candidate < best_cost:
                    best_cost = candidate
                    best_port = port

            if best_cost < INF:
                new_dv[dest] = best_cost
                new_ft[dest] = best_port

        changed = (new_dv != self.distance_vector or new_ft != self.forwarding_table)
        self.distance_vector = new_dv
        self.forwarding_table = new_ft
        return changed

    def handle_packet(self, port, packet):
        if packet.is_traceroute:
            if packet.dst_addr in self.forwarding_table:
                self.send(self.forwarding_table[packet.dst_addr], packet)
        else:
            try:
                received_dv = json.loads(packet.content)
            except (json.JSONDecodeError, TypeError):
                return

            neighbor = packet.src_addr
            received_dv.pop(self.addr, None)
            old_dv = self.neighbor_dvs.get(neighbor)
            self.neighbor_dvs[neighbor] = received_dv

            if received_dv != old_dv:
                if self.recompute():
                    self.broadcast_dv()

    def handle_new_link(self, port, endpoint, cost):
        self.neighbors[port] = (endpoint, cost)
        self.recompute()
        self.broadcast_dv()

    def handle_remove_link(self, port):
        if port not in self.neighbors:
            return
        neighbor, _ = self.neighbors.pop(port)
        self.neighbor_dvs.pop(neighbor, None)
        self.recompute()
        self.broadcast_dv()

    def handle_time(self, time_ms):
        if time_ms - self.last_time >= self.heartbeat_time:
            self.last_time = time_ms
            self.broadcast_dv()

    def __repr__(self):
        lines = [f"DVrouter(addr={self.addr})"]
        for dest, cost in sorted(self.distance_vector.items()):
            port = self.forwarding_table.get(dest, "-")
            lines.append(f"  {dest}: cost={cost}, port={port}")
        return "\n".join(lines)