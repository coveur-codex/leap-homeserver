// Rangierwerk rules, shared byte-for-byte with leap-homeserver.
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>

namespace rangierwerk {

using Index = uint8_t;
constexpr Index None = 255;
constexpr Index Engines = 4, MaxCars = 20, MaxVehicles = Engines + MaxCars;
constexpr Index MaxNodes = 112, MaxSwitches = 32, CargoTypes = 5, MaxOrders = 4;
constexpr uint32_t StepMs = 250, UnloadMs = 650;

enum class Track : uint8_t { Rail, Storage, Intake, Depot, Target };

struct Random {
  uint32_t state;
  uint32_t next() {
    if (!state)
      state = 0x9e3779b9;
    state ^= state << 13;
    state ^= state >> 17;
    return state ^= state << 5;
  }
  Index pick(Index count) { return next() % count; }
};

struct Node {
  Index x, y;
  Index links[3]{None, None, None}; // On a turnout: stem, straight, diverging.
  Index turnout = None;
  Track kind = Track::Rail;
  Index cargo = None;
};

struct Siding {
  Index turnout = None;
  Index inner = None, middle = None, end = None;
};

struct Layout {
  std::array<Node, MaxNodes> nodes{};
  std::array<Index, MaxSwitches> switches{};
  std::array<Index, 40> loop{};
  std::array<Siding, CargoTypes> targets{};
  std::array<Siding, Engines> depots{};
  std::array<Siding, 5> storage{};
  Siding intake{};
  Index count = 0, switchCount = 0, loopCount = 0, storageCount = 0;
  Index depotCount = 0, targetCount = 0, difficulty = 1;
  uint32_t seed = 0;

  bool isLoop(Index n) const {
    for (Index i = 0; i < loopCount; ++i)
      if (loop[i] == n)
        return true;
    return false;
  }

  bool adjacent(Index node, Index from) const {
    if (node >= count || from >= count)
      return false;
    for (Index neighbor : nodes[node].links)
      if (from == neighbor)
        return true;
    return false;
  }

  Index add(Index x, Index y, Track kind = Track::Rail, Index cargo = None) {
    if (count == MaxNodes)
      return None;
    nodes[count] = Node{x, y, {None, None, None}, None, kind, cargo};
    return count++;
  }

  bool link(Index a, Index b) {
    if (a >= count || b >= count || a == b || adjacent(a, b))
      return false;
    for (Index &left : nodes[a].links) {
      if (left != None)
        continue;
      for (Index &right : nodes[b].links) {
        if (right == None) {
          left = b;
          right = a;
          return true;
        }
      }
    }
    return false;
  }

  bool turnout(Index at, Index stem, Index straight, Index branch) {
    if (switchCount == MaxSwitches || nodes[at].turnout != None ||
        !adjacent(at, stem) || !adjacent(at, straight) || !adjacent(at, branch))
      return false;
    nodes[at].links[0] = stem;
    nodes[at].links[1] = straight;
    nodes[at].links[2] = branch;
    nodes[at].turnout = switchCount;
    switches[switchCount++] = at;
    return true;
  }

  bool addSiding(Siding &siding, Index at, Index stem, Index straight, bool upper,
                 Track kind, Index subtype) {
    const Index x = nodes[at].x;
    const Index firstX = upper ? x + 4 : x - 4;
    const Index endX = upper ? x + 9 : x - 9;
    siding = {at, add(firstX, upper ? 35 : 89), add(endX, upper ? 23 : 101, kind, subtype),
              add(endX, upper ? 11 : 113, kind, subtype)};
    if (siding.end == None)
      return false;
    // The inner approach remains clear of loading zones, and only the final
    // depot node is reserved for the corresponding locomotive.
    if (kind == Track::Depot)
      nodes[siding.middle].kind = Track::Rail;
    return link(at, siding.inner) && link(siding.inner, siding.middle) &&
           link(siding.middle, siding.end) && turnout(at, stem, straight, siding.inner);
  }

  bool build(uint32_t newSeed, Index level, bool multiplayer, bool fallback = false) {
    *this = Layout{};
    seed = newSeed;
    difficulty = level < 1 ? 1 : level > 4 ? 4 : level;
    Random random{fallback ? 0x317a901u : seed};
    const Index columns = fallback ? 15 : 13 + random.pick(3);
    const Index startX = 9, span = 220;
    Index rows[2][15]{};
    for (Index i = 0; i < columns; ++i) {
      const Index x = startX + i * span / (columns - 1);
      rows[0][i] = add(x, 47);
      rows[1][i] = add(x, 77);
    }
    Index far = add(startX + span, 62), near = add(startX, 62);
    for (Index i = 0; i < columns; ++i)
      loop[loopCount++] = rows[0][i];
    loop[loopCount++] = far;
    for (Index i = columns; i > 0; --i)
      loop[loopCount++] = rows[1][i - 1];
    loop[loopCount++] = near;
    for (Index i = 0; i < loopCount; ++i)
      if (!link(loop[i], loop[(i + 1) % loopCount]))
        return false;

    // Crossovers occupy their own columns. Their straight setting preserves the
    // complete runaround, even when every shed and storage road is in use.
    bool crossed[15]{};
    const Index crossovers = difficulty - 1;
    for (Index i = 0; i < crossovers; ++i) {
      Index col = 2 + i * 3 + random.pick(2);
      crossed[col] = true;
      Index top = rows[0][col], bottom = rows[1][col];
      Index center = add(nodes[top].x, 62);
      if (!link(top, center) || !link(center, bottom) ||
          !turnout(top, rows[0][col - 1], rows[0][col + 1], center) ||
          !turnout(bottom, rows[1][col + 1], rows[1][col - 1], center))
        return false;
    }

    struct Place { Index col, row; };
    Place places[26]{};
    Index free = 0;
    for (Index i = 1; i + 1 < columns; ++i) {
      if (crossed[i])
        continue;
      for (Index row = 0; row < 2; ++row)
        places[free++] = {i, row};
    }
    for (Index i = free; i > 1; --i) {
      const Index j = random.pick(i);
      const Place saved = places[i - 1];
      places[i - 1] = places[j];
      places[j] = saved;
    }

    Index used = 0;
    auto addAt = [&](Siding &siding, Track kind, Index subtype = None) {
      if (used == free)
        return false;
      const auto spot = places[used++];
      const auto row = rows[spot.row];
      const bool upper = spot.row == 0;
      return addSiding(siding, row[spot.col], row[upper ? spot.col - 1 : spot.col + 1],
                       row[upper ? spot.col + 1 : spot.col - 1], upper, kind, subtype);
    };
    depotCount = multiplayer ? Engines : 1;
    targetCount = difficulty == 1 ? (multiplayer ? 4 : 3) : difficulty == 2 ? 4 : CargoTypes;
    storageCount = 1 + difficulty;
    Index cargo[CargoTypes]{0, 1, 2, 3, 4};
    for (Index i = CargoTypes; i > 1; --i) {
      const Index j = random.pick(i);
      const Index saved = cargo[i - 1];
      cargo[i - 1] = cargo[j];
      cargo[j] = saved;
    }
    if (!addAt(intake, Track::Intake))
      return false;
    for (Index i = 0; i < depotCount; ++i)
      if (!addAt(depots[i], Track::Depot, i))
        return false;
    for (Index i = 0; i < targetCount; ++i)
      if (!addAt(targets[cargo[i]], Track::Target, cargo[i]))
        return false;
    for (Index i = 0; i < storageCount; ++i)
      if (!addAt(storage[i], Track::Storage))
        return false;
    // Left/top to right/bottom selection, independent of construction order.
    for (Index i = 1; i < switchCount; ++i) {
      const Index at = switches[i];
      Index j = i;
      while (j > 0) {
        const Node &left = nodes[switches[j - 1]], &right = nodes[at];
        if (left.x < right.x || (left.x == right.x && left.y < right.y))
          break;
        switches[j] = switches[j - 1];
        --j;
      }
      switches[j] = at;
    }
    for (Index i = 0; i < switchCount; ++i)
      nodes[switches[i]].turnout = i;
    return true;
  }

  Index route(Index at, Index from, uint32_t thrown) const {
    if (!adjacent(at, from))
      return None;
    const Node &n = nodes[at];
    if (n.turnout != None) {
      const Index active = n.links[1 + ((thrown >> n.turnout) & 1)];
      return from == n.links[0] ? active : from == active ? n.links[0] : None;
    }
    for (Index to : n.links)
      if (to != None && to != from)
        return to;
    return None;
  }

  bool accepts(Index at, Index from, uint32_t thrown) const {
    if (!adjacent(at, from))
      return false;
    const Node &n = nodes[at];
    return n.turnout == None || from == n.links[0] || from == n.links[1 + ((thrown >> n.turnout) & 1)];
  }

  bool validSiding(const Siding &s, Track kind) const {
    if (s.end >= count || s.turnout >= count || nodes[s.end].kind != kind ||
        !isLoop(s.turnout) || nodes[s.turnout].turnout >= switchCount)
      return false;
    const uint32_t diverge = 1u << nodes[s.turnout].turnout;
    const Index stem = nodes[s.turnout].links[0];
    if (route(s.turnout, stem, diverge) != s.inner ||
        route(s.turnout, s.inner, diverge) != stem ||
        route(s.inner, s.turnout, 0) != s.middle ||
        route(s.middle, s.inner, 0) != s.end ||
        route(s.middle, s.end, 0) != s.inner)
      return false;
    // A loco and two cars can leave the turnout behind them before reversing.
    Index approach = stem, previous = s.turnout;
    for (Index i = 0; i < 3; ++i) {
      if (!isLoop(approach))
        return false;
      Index next = route(approach, previous, 0);
      previous = approach;
      approach = next;
    }
    return true;
  }

  // Constructive check. A rearward move clears an occupied source road with up
  // to two cars. The straight runaround reaches every target's facing stem;
  // reversing there and throwing the turnout admits the same consist.
  bool valid() const {
    if (count > MaxNodes || !loopCount || !validSiding(intake, Track::Intake))
      return false;
    for (Index i = 0; i < loopCount; ++i) {
      const Index next = loop[(i + 1) % loopCount], prev = loop[(i + loopCount - 1) % loopCount];
      if (route(loop[i], prev, 0) != next || route(loop[i], next, 0) != prev)
        return false;
    }
    for (Index i = 0; i < depotCount; ++i)
      if (!validSiding(depots[i], Track::Depot))
        return false;
    for (Index i = 0; i < storageCount; ++i)
      if (!validSiding(storage[i], Track::Storage))
        return false;
    Index destinations = 0;
    for (Index i = 0; i < CargoTypes; ++i)
      if (targets[i].end != None) {
        if (!validSiding(targets[i], Track::Target) || nodes[targets[i].end].cargo != i)
          return false;
        ++destinations;
      }
    if (destinations != targetCount)
      return false;
    bool seen[MaxNodes]{};
    for (Index i = 0; i < loopCount; ++i)
      seen[loop[i]] = true;
    for (Index pass = 0; pass < 4; ++pass)
      for (Index n = 0; n < count; ++n) {
        for (Index next : nodes[n].links)
          if (next != None) {
            if (!adjacent(next, n))
              return false;
            if (seen[n])
              seen[next] = true;
          }
      }
    for (Index n = 0; n < count; ++n) {
      if (!seen[n])
        return false;
      for (Index left = 0; left < n; ++left)
        if (nodes[left].x == nodes[n].x && nodes[left].y == nodes[n].y)
          return false;
    }
    return true;
  }

  bool generate(uint32_t newSeed, Index level, bool multiplayer, uint8_t attempts = 4) {
    if (attempts > 4)
      attempts = 4;
    for (uint8_t attempt = 0; attempt < attempts; ++attempt)
      if (build(newSeed + 0x9e3779b9u * attempt, level, multiplayer) && valid()) {
        seed = newSeed;
        return true;
      }
    return build(newSeed, level, multiplayer, true) && valid();
  }
};

struct Vehicle {
  uint32_t id = 0;  // Stable throughout the card, including after handoff.
  uint32_t unloading = 0;
  Index node = None, oldNode = None, anchor = None;
  Index links[2]{None, None};
  Index cargo = None;
  int8_t anchorDirection = -1;
};

struct Order {
  uint32_t id = 0;
  Index cargo = None, count = 0, delivered = 0;
  bool open() const { return id && delivered < count; }
};

enum class Move : uint8_t { Stopped, Travel, Coupled };

struct Consist {
  Index vehicles[5]{None, None, None, None, None};
  Index size = 0, engine = None;
};

inline Consist inspectConsist(const std::array<Vehicle, MaxVehicles> &vehicles, Index slot) {
  Consist result;
  if (slot >= Engines || !vehicles[slot].id)
    return result;
  auto other = [&](Index at, Index previous) {
    const auto &v = vehicles[at];
    return v.links[0] == previous ? v.links[1] : v.links[0];
  };
  const Vehicle &loco = vehicles[slot];
  Index rear = None;
  for (Index next : loco.links) {
    if (next >= MaxVehicles || !vehicles[next].id)
      continue;
    const int side = vehicles[next].node == loco.anchor ? loco.anchorDirection : -loco.anchorDirection;
    if (side == -1)
      rear = next;
  }
  Index start = slot;
  for (Index previous = slot, steps = 0; rear < MaxVehicles && steps < 4; ++steps) {
    start = rear;
    rear = other(rear, previous);
    previous = start;
  }
  Index previous = None;
  for (Index at = start; at < MaxVehicles && vehicles[at].id && result.size < 5;) {
    if (at == slot)
      result.engine = result.size;
    result.vehicles[result.size++] = at;
    const Index next = other(at, previous);
    previous = at;
    at = next;
  }
  return result;
}

class Yard {
  uint32_t nextId = 0, age = 0;
  Random random{0};
  Index desired = 1;
  std::array<Index, MaxNodes> occupied{};
  void attach(Index a, Index b) {
    for (auto &link : vehicles[a].links)
      if (link == None) {
        link = b;
        break;
      }
    for (auto &link : vehicles[b].links)
      if (link == None) {
        link = a;
        break;
      }
  }
  void detach(Index a, Index b) {
    for (auto &link : vehicles[a].links)
      if (link == b)
        link = None;
    for (auto &link : vehicles[b].links)
      if (link == a)
        link = None;
  }

  Index other(Index at, Index previous) const {
    const Vehicle &v = vehicles[at];
    return v.links[0] == previous ? v.links[1] : v.links[0];
  }

  Index engineFor(Index car) const {
    if (car < Engines)
      return car;
    for (Index next : vehicles[car].links) {
      Index previous = car;
      for (Index steps = 0; next != None && steps < 4; ++steps) {
        if (next < Engines)
          return next;
        const Index following = other(next, previous);
        previous = next;
        next = following;
      }
    }
    return None;
  }

  void unloadParked() {
    for (Index i = Engines; i < MaxVehicles; ++i) {
      Vehicle &car = vehicles[i];
      if (!car.id || car.unloading || engineFor(i) != None)
        continue;
      const Node &node = layout.nodes[car.node];
      if (node.kind != Track::Target || node.cargo != car.cargo)
        continue;
      for (Order &order : orders) {
        if (!order.open() || order.cargo != car.cargo)
          continue;
        ++order.delivered;
        ++delivered;
        while (car.links[0] != None || car.links[1] != None)
          detach(i, car.links[0] != None ? car.links[0] : car.links[1]);
        car.unloading = UnloadMs;
        break;
      }
    }
  }

  void addOrders() {
    bool taken[CargoTypes]{};
    Index open = 0;
    for (const auto &order : orders) {
      if (order.open()) {
        taken[order.cargo] = true;
        ++open;
      }
    }
    for (auto &order : orders) {
      if (open >= desired || order.open())
        continue;
      Index types[CargoTypes]{}, available = 0;
      for (Index cargo = 0; cargo < CargoTypes; ++cargo)
        if (!taken[cargo] && layout.targets[cargo].end != None)
          types[available++] = cargo;
      if (!available)
        return;
      const auto cargo = types[random.pick(available)];
      const Index maxCount = layout.difficulty == 1 ? 2 : 3;
      order = {++nextId, cargo, Index(1 + random.pick(maxCount)), 0};
      taken[cargo] = true;
      ++open;
    }
  }

  bool spawn(Index at, Index cargo) {
    if (at >= layout.count || occupied[at] != None)
      return false;
    for (Index i = Engines; i < MaxVehicles; ++i) {
      Vehicle &v = vehicles[i];
      if (v.id)
        continue;
      v = Vehicle{};
      v.id = ++nextId;
      v.node = at;
      v.anchor = layout.nodes[at].links[0];
      v.cargo = cargo;
      occupied[at] = i;
      return true;
    }
    return false;
  }

  void replenish() {
    const Siding &s = layout.intake;
    if (age < 850 || occupied[s.inner] != None || occupied[s.middle] != None || occupied[s.end] != None ||
        occupied[s.turnout] != None)
      return;
    Index stock[CargoTypes]{};
    Index cars = 0;
    for (Index i = Engines; i < MaxVehicles; ++i) {
      if (vehicles[i].id && !vehicles[i].unloading) {
        ++stock[vehicles[i].cargo];
        ++cars;
      }
    }
    // Each type has at most three live cars, including inactive orders' stock.
    // Fifteen is therefore possible only when every outstanding order is supplied.
    if (cars >= 3 * CargoTypes)
      return;
    for (const auto &order : orders)
      if (order.open() && order.count - order.delivered > stock[order.cargo] &&
          spawn(s.end, order.cargo)) {
        age = 0;
        return;
      }
  }

public:
  Layout layout{};
  std::array<Vehicle, MaxVehicles> vehicles{};
  std::array<Order, MaxOrders> orders{};
  uint32_t thrown = 0, delivered = 0;

  bool reset(uint32_t seed, Index difficulty, bool multiplayer) {
    if (!layout.generate(seed, difficulty, multiplayer))
      return false;
    vehicles.fill(Vehicle{});
    orders.fill(Order{});
    occupied.fill(None);
    random = Random{seed ^ 0xa7d0d143u};
    nextId = age = thrown = delivered = 0;
    desired = multiplayer ? 3 : layout.difficulty > 3 ? 3 : layout.difficulty;
    addOrders();
    Index active[CargoTypes]{}, count = 0;
    for (const auto &order : orders)
      if (order.open())
        active[count++] = order.cargo;
    Index stock[CargoTypes]{};
    auto initialCar = [&](Index at, Index cargo) {
      if (stock[cargo] == 3) {
        for (Index other = 0; other < CargoTypes; ++other)
          if (stock[other] < 3 && layout.targets[other].end != None && other != cargo) {
            cargo = other;
            break;
          }
      }
      if (stock[cargo] < 3 && spawn(at, cargo))
        ++stock[cargo];
    };
    for (Index i = 0; i < layout.storageCount; ++i) {
      const Siding &road = layout.storage[i];
      initialCar(road.end, active[i % count]);
      if (layout.difficulty >= 2 && (i < layout.difficulty - 1 || layout.difficulty == 4))
        initialCar(road.middle, active[(i + 1) % count]);
    }
    return true;
  }

  void orderCount(Index count) {
    desired = count < 1 ? 1 : count > MaxOrders ? MaxOrders : count;
    addOrders();
  }

  bool join(Index slot) {
    if (slot >= layout.depotCount)
      return false;
    if (vehicles[slot].id)
      return true;
    const Siding &depot = layout.depots[slot];
    if (occupied[depot.end] != None)
      return false;
    Vehicle &v = vehicles[slot];
    v = Vehicle{};
    v.id = ++nextId;
    v.node = depot.end;
    v.anchor = depot.middle;
    v.anchorDirection = 1;
    occupied[v.node] = slot;
    return true;
  }

  void leave(Index slot) {
    if (slot >= Engines || !vehicles[slot].id)
      return;
    Vehicle &v = vehicles[slot];
    for (Index next : v.links)
      if (next != None)
        detach(slot, next);
    occupied[v.node] = None;
    v = Vehicle{};
    unloadParked();
  }

  bool recover(Index slot) {
    if (slot >= layout.depotCount || !vehicles[slot].id || vehicles[slot].node == layout.depots[slot].end)
      return false;
    leave(slot);
    return join(slot);
  }

  bool toggle(Index index) {
    if (index >= layout.switchCount || occupied[layout.switches[index]] != None)
      return false;
    thrown ^= 1u << index;
    return true;
  }

  Consist consist(Index slot) const { return inspectConsist(vehicles, slot); }

  bool split(Index slot, uint32_t aId, uint32_t bId) {
    const Consist train = consist(slot);
    for (Index i = 1; i < train.size; ++i) {
      const Index a = train.vehicles[i - 1], b = train.vehicles[i];
      if ((vehicles[a].id == aId && vehicles[b].id == bId) ||
          (vehicles[a].id == bId && vehicles[b].id == aId)) {
        detach(a, b);
        unloadParked();
        return true;
      }
    }
    return false;
  }

  Move drive(Index slot, int direction) {
    const Consist train = consist(slot);
    if (!train.size || (direction != 1 && direction != -1))
      return Move::Stopped;
    const bool front = direction == 1;
    const Index size = train.size, leader = train.vehicles[front ? size - 1 : 0];
    const Index current = vehicles[leader].node;
    Index inward = vehicles[slot].anchor;
    if (size > 1)
      inward = vehicles[train.vehicles[front ? size - 2 : 1]].node;
    const Index next = size == 1 && direction == vehicles[slot].anchorDirection
                           ? inward : layout.route(current, inward, thrown);
    if (!layout.accepts(next, current, thrown))
      return Move::Stopped;

    if (occupied[next] != None) {
      const Index car = occupied[next];
      if (car < Engines || vehicles[car].unloading || engineFor(car) != None)
        return Move::Stopped;
      const auto &parked = vehicles[car];
      if (parked.links[0] != None && parked.links[1] != None)
        return Move::Stopped;
      const Index behind = other(car, None);
      if (behind != None && layout.route(next, current, thrown) != vehicles[behind].node)
        return Move::Stopped;
      Index count = 0, previous = None;
      for (Index part = car; part != None;) {
        if (++count + size > 5)
          return Move::Stopped;
        const Index following = other(part, previous);
        previous = part;
        part = following;
      }
      attach(leader, car);
      return Move::Coupled;
    }

    const Node &destination = layout.nodes[next];
    if (destination.kind == Track::Depot && (size != 1 || destination.cargo != slot))
      return Move::Stopped;
    for (Index i = 0; i < size; ++i) {
      Vehicle &v = vehicles[train.vehicles[i]];
      v.oldNode = v.node;
      occupied[v.node] = None;
    }
    for (Index i = 0; i < size; ++i) {
      const Index order = front ? size - 1 - i : i;
      const Index id = train.vehicles[order];
      Vehicle &v = vehicles[id];
      v.node = i ? vehicles[train.vehicles[front ? order + 1 : order - 1]].oldNode : next;
      v.anchor = v.oldNode;
      v.anchorDirection = -direction;
      occupied[v.node] = id;
    }
    return Move::Travel;
  }

  void tick(uint32_t ms) {
    age = ms >= 850 - age ? 850 : age + ms;
    for (Index i = Engines; i < MaxVehicles; ++i) {
      Vehicle &v = vehicles[i];
      if (!v.unloading)
        continue;
      if (ms >= v.unloading) {
        occupied[v.node] = None;
        v = Vehicle{};
      } else {
        v.unloading -= ms;
      }
    }
    addOrders();
    unloadParked();
    replenish();
  }
};

} // namespace rangierwerk
