/* SPDX-License-Identifier: Apache-2.0 */
#include <inttypes.h>
#include <string.h>

#include "mshv/test.h"

test_result_t mshv_roundtrip(struct mshv_fixture *f, unsigned count, uint64_t seed)
{
    const uint32_t names[] = {VV_RAX, VV_RCX, VV_RDX, VV_RBX};
    struct hv_register_assoc regs[4] = {0};
    struct mshv_vp_registers args = {.count = count, .regs = regs};
    uint64_t expected[4];

    if (count == 0 || count > 4)
        TFAIL("internal roundtrip count: expected 1..4, actual %u", count);
    for (unsigned i = 0; i < count; ++i) {
        regs[i].name = names[i];
        expected[i] = seed ^ (0x1111111111111111ULL * i);
        regs[i].value.reg64 = expected[i];
    }
    if (mshv_expect_ioctl(f->vp, MSHV_SET_VP_REGISTERS, &args,
                          "MSHV_SET_VP_REGISTERS GPRs", 0) != TEST_PASS)
        return TEST_FAIL;
    for (unsigned i = 0; i < count; ++i)
        memset(&regs[i].value, 0xa5, sizeof(regs[i].value));
    if (mshv_expect_ioctl(f->vp, MSHV_GET_VP_REGISTERS, &args,
                          "MSHV_GET_VP_REGISTERS GPRs", 0) != TEST_PASS)
        return TEST_FAIL;
    if (args.count != count || args.padding != 0 || args.regs != regs)
        TFAIL("GET register envelope changed: expected count=%u padding=0 regs=%p, "
              "actual count=%u padding=%u regs=%p",
              count, (void *)regs, args.count, args.padding, (void *)args.regs);
    for (unsigned i = 0; i < count; ++i) {
        if (regs[i].name != names[i] || regs[i].reserved1 || regs[i].reserved2)
            TFAIL("GET association %u: expected name=0x%x and MBZ fields; "
                  "actual name=0x%x reserved1=0x%x reserved2=0x%" PRIx64,
                  i, names[i], regs[i].name, regs[i].reserved1, regs[i].reserved2);
        if (regs[i].value.reg64 != expected[i])
            TFAIL("GET register 0x%x: expected 0x%016" PRIx64 ", actual 0x%016" PRIx64,
                  names[i], expected[i], regs[i].value.reg64);
    }
    return TEST_PASS;
}
