import simpy
import random


def normal_time(mean=4.0, std_dev=1.0):
    """Return a truncated normal sample (no negative times)."""
    val = random.gauss(mean, std_dev)
    return max(val, 0.0)


def exponential_time(mean=3.0):
    """Return an exponential sample with given mean."""
    return random.expovariate(1.0 / mean)


def normal_delay(mean=2.0, std_dev=1.0):
    """Helper for normal restock delays."""
    val = random.gauss(mean, std_dev)
    return max(val, 0.0)


class Station:
    def __init__(self, env, station_id, factory, fail_prob, fix_time_mean=3.0, work_time_mean=4.0):
        self.env = env
        self.station_id = station_id
        self.resource = simpy.Resource(env, capacity=1)  # Only 1 item at a time
        self.fail_prob = fail_prob
        self.fix_time_mean = fix_time_mean
        self.work_time_mean = work_time_mean
        self.total_waiting_time = 0

        # To handle "check every 5 products" logic:
        self.count_since_check = 0  # how many have been processed since last failure check
        self.is_broken = False
        self.bin = simpy.Container(env, init=25)

        # For data collection:
        self.total_downtime = 0.0
        self.last_break_time = None  # when station broke
        self.num_breakdowns = 0
        self.total_processing_time = 0.0
        self.busy_time = 0.0
        self.last_start_busy = 0.0  # track when station last started processing an item
        self.env.process(self.restock_process(factory))
        self.restocking_time = 0.0

    def start_processing(self):
        self.last_start_busy = self.env.now

    def finish_processing(self):
        self.busy_time += (self.env.now - self.last_start_busy)

    def check_for_failure(self):
        """Check if station fails after 5 items processed."""
        self.count_since_check += 1
        if self.count_since_check >= 5:
            # Reset the counter
            self.count_since_check = 0
            # Probability of failure
            if random.random() < self.fail_prob:
                # Trigger breakdown
                return True
        return False

    def restock_process(self, factory):
        while True:
            if self.bin.level < 5:
                with factory.restock_devices.request() as req:
                    yield req
                    start_restocking_time = self.env.now
                    delay = normal_time(mean=2.0, std_dev=1.0)
                    yield self.env.timeout(delay)
                    self.restocking_time += (self.env.now - start_restocking_time)
                    yield self.bin.put(25)
            else:
                # Check less frequently if still enough material
                yield self.env.timeout(1.0)

    def break_station(self):
        """Simulate the breakdown."""
        self.is_broken = True
        self.num_breakdowns += 1
        self.last_break_time = self.env.now

        # Maintenance takes exponentially distributed time
        fix_time = exponential_time(self.fix_time_mean)
        yield self.env.timeout(fix_time)

        # Station is repaired
        self.is_broken = False
        down_duration = self.env.now - self.last_break_time
        self.total_downtime += down_duration
        self.last_break_time = None

    def process_item(self):
        while self.is_broken:
            yield self.env.timeout(0.1)

        yield self.bin.get(1)

        self.start_processing()
        processing_time = normal_time(mean=self.work_time_mean, std_dev=1.0)
        yield self.env.timeout(processing_time)
        self.finish_processing()

        if self.check_for_failure():
            yield self.env.process(self.break_station())


class Factory(object):
    def __init__(self, env: simpy.Environment):
        self._env = env
        self.items = 0
        stations = []
        self.restock_devices = simpy.Resource(env, capacity=3)
        self.total_produced = 0
        self.faulty_products = 0
        self.accidents_occurred = 0
        fail_probs = [0.02, 0.01, 0.05, 0.15, 0.07, 0.06]
        for i in range(6):
            stations.append(Station(env, i+1, self, fail_prob=fail_probs[i]))
        self.stations = stations
        self.action = env.process(self.production())
        self.total_wait_time = 0.0
        self.num_waits = 0

    def production(self):
        while True:
            self.items += 1
            waiting_time = abs(random.normalvariate(3, 0.5))
            yield self._env.timeout(waiting_time)
            item_id = self.items
            self._env.process(self.item_processor(item_id))

    def item_processor(self, item_id: int):

        yield self._env.process(self.process_at_station(self.stations[0], item_id))

        yield self._env.process(self.process_at_station(self.stations[1], item_id))

        yield self._env.process(self.process_at_station(self.stations[2], item_id))

        req4 = self.stations[3].resource.request()
        req5 = self.stations[4].resource.request()
        res = yield req4 | req5
        if req4 in res:
            yield self._env.process(self.process_at_station(self.stations[3], item_id, request=req4))
            yield self._env.process(self.process_at_station(self.stations[4], item_id, request=req5))
        else:
            yield self._env.process(self.process_at_station(self.stations[4], item_id, request=req5))
            yield self._env.process(self.process_at_station(self.stations[3], item_id, request=req4))
        yield self._env.process(self.process_at_station(self.stations[5], item_id))

        if random.random() < 0.05:
            self.faulty_products += 1
        else:
            self.total_produced += 1

    def waiting_end(self, wait_start, station):
        if station.station_id != 1:
            wait_end = self._env.now
            wait_time = wait_end - wait_start
            print(f"wait time: {wait_time}")
            self.total_wait_time += wait_time
            station.total_waiting_time += wait_time
            self.num_waits += 1


    def process_at_station(self, station, item_id, request=None):
        wait_start = self._env.now
        if request is not None:
            yield request
            self.waiting_end(wait_start, station)
            yield self._env.process(station.process_item())
            station.resource.release(request)
        else:
            with station.resource.request() as req:
                yield req
                self.waiting_end(wait_start,station)
                yield self._env.process(station.process_item())


        print(f"Time {self._env.now:.2f}: Item {item_id} finished at Station {station.station_id}")




env = simpy.Environment()
factory = Factory(env)
print()
# env.process(customer_arrival(env))
# env.process(alarm(env, 30, bank))
env.run(until=5000)
print(f"Simulation ended at time={env.now}")
print(f"Total produced (non-faulty) items: {factory.total_produced}")
print(f"Faulty products: {factory.faulty_products}")
print(f"Faulty products rate: {(factory.faulty_products/(factory.faulty_products + factory.total_produced))*100:.2f}%")
print(f"Total time spent waiting for a Station: {factory.total_wait_time:.2f}")

print(f"Average bottleneck delay: {factory.total_wait_time/factory.num_waits:.2f} time units")
total_restocking_time = 0
for i, station in enumerate(factory.stations):
    occupancy_rate = station.busy_time / env.now
    total_restocking_time += station.restocking_time
    print(f"Station {station.station_id}:")
    print(f"  - Occupancy (busy) rate: {occupancy_rate * 100:.2f}%")
    print(f"  - Total time getting fixed: {station.total_downtime:.2f}")
    print(f"  - Number of breakdowns: {station.num_breakdowns}")
    print(f"  - Total time items waited to be processed: {station.total_waiting_time:.2f}")
print(f"Restocking device occupancy (busy) rate: {(total_restocking_time / env.now)*100:.2f}%")
