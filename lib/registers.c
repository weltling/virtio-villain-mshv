/* SPDX-License-Identifier: Apache-2.0 */
/*
 * Shared general purpose register (GPR) checks.
 * Use RAX, RCX, RDX, RBX with distinct seed-derived values. Poison receive
 * slots before GET, then require exact lower 64-bit values and register names.
 * Separate SET and GET checks allow observation without overwriting state.
 * The upper half of each 128-bit ABI value slot is not asserted for GPRs.
 * Also require unchanged request count, padding and array pointer, plus zero
 * must-be-zero (MBZ) association fields. Both IOCTLs must return zero.
 * These checks exercise register access, not virtual processor execution.
 */
#include <inttypes.h>
#include <string.h>

#include "lib/mshv.h"

static test_result_t access_gprs(struct mshv_fixture *f, unsigned count,
                                 uint64_t seed, unsigned long request)
{
    const uint32_t names[] = {VV_RAX, VV_RCX, VV_RDX, VV_RBX};
    enum { REGISTER_COUNT = sizeof(names) / sizeof(names[0]) };
    struct hv_register_assoc regs[REGISTER_COUNT] = {0};
    struct mshv_vp_registers args = {.count = count, .regs = regs};
    uint64_t expected[REGISTER_COUNT];
    const char *operation = request == MSHV_SET_VP_REGISTERS ? "SET" : "GET";

    if (count == 0 || count > REGISTER_COUNT)
        TFAIL("internal register count: expected 1..%u, actual %u",
              (unsigned)REGISTER_COUNT, count);
    for (unsigned i = 0; i < count; ++i) {
        regs[i].name = names[i];
        expected[i] = seed ^ (VV_GPR_REGISTER_STRIDE * i);
        if (request == MSHV_SET_VP_REGISTERS)
            regs[i].value.reg64 = expected[i];
        else
            memset(&regs[i].value, 0xa5, sizeof(regs[i].value));
    }
    if (mshv_expect_ioctl(f->vp, request, &args,
                          request == MSHV_SET_VP_REGISTERS ?
                          "MSHV_SET_VP_REGISTERS GPRs" : "MSHV_GET_VP_REGISTERS GPRs",
                          0) != TEST_PASS)
        return TEST_FAIL;
    if (args.count != count || args.padding != 0 || args.regs != regs)
        TFAIL("%s fd=%d register envelope changed: expected count=%u padding=0 regs=%p, "
              "actual count=%u padding=%u regs=%p",
              operation, f->vp, count, (void *)regs, args.count,
              args.padding, (void *)args.regs);
    for (unsigned i = 0; i < count; ++i) {
        if (regs[i].name != names[i] || regs[i].reserved1 || regs[i].reserved2)
            TFAIL("%s fd=%d association %u: expected name=0x%x and MBZ fields; "
                  "actual name=0x%x reserved1=0x%x reserved2=0x%" PRIx64,
                  operation, f->vp, i, names[i], regs[i].name,
                  regs[i].reserved1, regs[i].reserved2);
        if (regs[i].value.reg64 != expected[i])
            TFAIL("%s fd=%d register 0x%x: expected 0x%016" PRIx64 ", actual 0x%016" PRIx64,
                  operation, f->vp, names[i], expected[i], regs[i].value.reg64);
    }
    return TEST_PASS;
}

test_result_t mshv_set_gprs(struct mshv_fixture *f, unsigned count, uint64_t seed)
{
    return access_gprs(f, count, seed, MSHV_SET_VP_REGISTERS);
}

test_result_t mshv_check_gprs(struct mshv_fixture *f, unsigned count, uint64_t seed)
{
    return access_gprs(f, count, seed, MSHV_GET_VP_REGISTERS);
}

test_result_t mshv_roundtrip(struct mshv_fixture *f, unsigned count, uint64_t seed)
{
    if (mshv_set_gprs(f, count, seed) != TEST_PASS)
        return TEST_FAIL;
    return mshv_check_gprs(f, count, seed);
}
