from router import Router
from packet import Packet
import heapq
import json


class LSrouter(Router):
    def __init__(self, addr, heartbeat_time):
        Router.__init__(self, addr)
        self.heartbeat_time = heartbeat_time
        self.last_time = 0
        self.network_graph = {addr: {}}
        self.sequence_numbers = {addr: 0}
        self.forwarding_table = {}
        self.link_costs = {}            # port -> (endpoint, cost)
        self._endpoint_to_port = {}     # endpoint -> port

    # ------------------------------------------------------------------ #
    #  Packet helpers                                                    #
    # ------------------------------------------------------------------ #

    def _build_routing_packet(self):
        payload = {
            'src': self.addr,
            'seq': self.sequence_numbers[self.addr],
            'ls':  dict(self.network_graph[self.addr]),
        }
        return Packet(Packet.ROUTING, self.addr, None, content=json.dumps(payload))

    def _broadcast_link_state(self):
        if not self.links:
            return
        packet = self._build_routing_packet()
        for port in self.links:
            self.send(port, packet)

    def _flood(self, packet, incoming_port):
        for port in self.links:
            if port != incoming_port:
                self.send(port, packet)

    # ------------------------------------------------------------------ #
    #  Topology                                                          #
    # ------------------------------------------------------------------ #

    def _update_network_graph(self, src, new_ls, seq):
        known_seq = self.sequence_numbers.get(src)
        if known_seq is not None and seq <= known_seq:
            return False                        

        self.sequence_numbers[src] = seq        

        if self.network_graph.get(src) == new_ls:
            return False                        

        self.network_graph[src] = new_ls
        return True

    def _dijkstra(self):
        """
        Phiên bản tối ưu: Không clone đồ thị, sử dụng lười (lazy initialization) cho dist.
        """
        # Sử dụng trực tiếp self.network_graph để tiết kiệm tài nguyên gán/copy tài nguyên
        graph = self.network_graph

        dist = {self.addr: 0}
        parent = {}
        heap = [(0, self.addr)]
        visited = set()

        while heap:
            d, u = heapq.heappop(heap)
            if u in visited:
                continue
            visited.add(u)

            # Duyệt qua các node hàng xóm từ góc nhìn của node u
            for v, w in graph.get(u, {}).items():
                nd = d + w
                # Lazy check: nếu v chưa có trong dist tức là khoảng cách bằng vô cùng (inf)
                if nd < dist.get(v, float('inf')):
                    dist[v] = nd
                    parent[v] = u
                    heapq.heappush(heap, (nd, v))

        result = {}
        # Chỉ duyệt qua các node thực sự kết nối được (nằm trong cây parent)
        for dst in parent:
            if dst == self.addr:
                continue
                
            hop = dst
            while parent.get(hop) != self.addr:
                hop = parent[hop]
                
            if hop in self._endpoint_to_port:
                result[dst] = (dist[dst], hop)

        return result

    def _update_forwarding_table(self):
        self.forwarding_table = {
            dst: self._endpoint_to_port[next_hop]
            for dst, (_, next_hop) in self._dijkstra().items()
            if next_hop in self._endpoint_to_port
        }

    # ------------------------------------------------------------------ #
    #  Event handlers                                                    #
    # ------------------------------------------------------------------ #

    def handle_packet(self, port, packet):
        if packet.kind != Packet.ROUTING:
            out = self.forwarding_table.get(packet.dst_addr)
            if out is not None:
                self.send(out, packet)
            return

        if not packet.content:
            return
        try:
            data = json.loads(packet.content)
            src, seq, ls = data['src'], data['seq'], data['ls']
        except (json.JSONDecodeError, KeyError, TypeError):
            return

        if self._update_network_graph(src, ls, seq):
            self._flood(packet, port)
            self._update_forwarding_table()

    def handle_new_link(self, port, endpoint, cost):
        self.link_costs[port] = (endpoint, cost)
        self._endpoint_to_port[endpoint] = port
        self.network_graph[self.addr][endpoint] = cost
        self.sequence_numbers[self.addr] += 1
        self._update_forwarding_table()
        self._broadcast_link_state()

    def handle_remove_link(self, port):
        if port not in self.link_costs:
            return
        endpoint, _ = self.link_costs.pop(port)
        self._endpoint_to_port.pop(endpoint, None)
        self.network_graph[self.addr].pop(endpoint, None)
        
        # Giữ nguyên thiết kế chuẩn của bạn: Không can thiệp sửa LSA của node khác ở đây
        self.sequence_numbers[self.addr] += 1
        self._update_forwarding_table()
        self._broadcast_link_state()

    def handle_time(self, time_ms):
        if time_ms - self.last_time >= self.heartbeat_time:
            self.last_time = time_ms
            self._broadcast_link_state()

    def __repr__(self):
        return (
            f"LSrouter(addr={self.addr}, "
            f"known={len(self.network_graph)}, "
            f"routes={len(self.forwarding_table)})"
        )