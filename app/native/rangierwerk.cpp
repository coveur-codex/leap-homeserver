#include "Yard.h"
#include <new>

using namespace rangierwerk;

static_assert(Engines == 4 && MaxVehicles == 24 && MaxOrders == 4 && StepMs == 250,
              "Update the Python ABI before changing snapshot capacities or timing");

extern "C" {
Yard *rw_create() { return new (std::nothrow) Yard; }
void rw_destroy(Yard *yard) { delete yard; }
bool rw_reset(Yard *yard, uint32_t seed, uint8_t difficulty) { return yard->reset(seed, difficulty, true); }
bool rw_join(Yard *yard, uint8_t slot) { return yard->join(slot); }
void rw_leave(Yard *yard, uint8_t slot) { yard->leave(slot); }
bool rw_recover(Yard *yard, uint8_t slot) { return yard->recover(slot); }
void rw_order_count(Yard *yard, uint8_t count) { yard->orderCount(count); }
bool rw_turnout(Yard *yard, uint8_t index) { return yard->toggle(index); }
bool rw_split(Yard *yard, uint8_t slot, uint32_t a, uint32_t b) { return yard->split(slot, a, b); }
uint8_t rw_drive(Yard *yard, uint8_t slot, int direction) { return uint8_t(yard->drive(slot, direction)); }
void rw_tick(Yard *yard, uint32_t ms) { yard->tick(ms); }

void rw_snapshot(const Yard *yard, uint32_t *header, uint32_t *vehicles, uint32_t *orders) {
  header[0] = yard->thrown;
  header[1] = yard->delivered;
  for (const auto &v : yard->vehicles) {
    *vehicles++ = v.id;
    *vehicles++ = v.node;
    *vehicles++ = v.anchor;
    *vehicles++ = v.cargo;
    *vehicles++ = v.unloading;
    *vehicles++ = v.links[0];
    *vehicles++ = v.links[1];
    *vehicles++ = v.anchorDirection == 1;
  }
  for (const auto &o : yard->orders) {
    *orders++ = o.id;
    *orders++ = o.cargo;
    *orders++ = o.count;
    *orders++ = o.delivered;
  }
}
}
