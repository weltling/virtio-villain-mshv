/* SPDX-License-Identifier: Apache-2.0 */
/*
 * TL0001: Scalar zero extension and full XMM register values.
 *
 * TLFS 6.0b section 7.8 requires values smaller than 128 bits to be
 * zero extended. It defines the GPR and XMM register names and values.
 * Requires x86-64 SSE state and parent register access. No VP execution.
 */
#include <inttypes.h>
#include <string.h>

#include "lib/mshv.h"

static test_result_t check_values(const uint32_t *names,
                                  const union hv_register_value *expected,
                                  const union hv_register_value *actual,
                                  unsigned count, const char *operation)
{
    for (unsigned i = 0; i < count; ++i) {
        if (actual[i].words[0] != expected[i].words[0] ||
            actual[i].words[1] != expected[i].words[1])
            TFAIL("%s register 0x%x: expected high=0x%016" PRIx64 " low=0x%016" PRIx64
                  ", actual high=0x%016" PRIx64 " low=0x%016" PRIx64,
                  operation, names[i], expected[i].words[1], expected[i].words[0],
                  actual[i].words[1], actual[i].words[0]);
    }
    return TEST_PASS;
}

static test_result_t register_values(struct mshv_fixture *f)
{
    const uint32_t names[] = {VV_RAX, VV_RCX, VV_RDX, VV_RBX, VV_XMM0, VV_XMM1};
    enum { COUNT = sizeof(names) / sizeof(names[0]) };
    const uint64_t seeds[] = {VV_GPR_SEED_ASCENDING, VV_GPR_SEED_DESCENDING};
    struct hv_register_assoc regs[COUNT] = {0};
    union hv_register_value expected[COUNT], actual[COUNT];
    struct mshv_vp_registers args = {.count = COUNT, .regs = regs};

    if (mshv_create_configured(f, VV_MSHV_PARTITION_FLAGS_NONE, VV_TLFS_BASIC_FEATURES) != TEST_PASS)
        return TEST_FAIL;
    for (unsigned cycle = 0; cycle < sizeof(seeds) / sizeof(seeds[0]); ++cycle) {
        for (unsigned i = 0; i < COUNT; ++i) {
            expected[i].words[0] = seeds[cycle] ^ (VV_GPR_REGISTER_STRIDE * i);
            expected[i].words[1] = i < 4 ? 0 : ~expected[i].words[0];
            regs[i].name = names[i];
            regs[i].value = expected[i];
        }
        if (cycle == 0) {
            if (mshv_set_registers(f->vp, 0, regs, COUNT) != TEST_PASS)
                return TEST_FAIL;
        } else if (mshv_expect_ioctl(f->vp, MSHV_SET_VP_REGISTERS, &args,
                                      "SET register encodings", 0) != TEST_PASS) {
            return TEST_FAIL;
        }
        memset(actual, 0xa5, sizeof(actual));
        if (mshv_get_registers(f->vp, 0, names, actual, COUNT) != TEST_PASS ||
            check_values(names, expected, actual, COUNT, "hypercall GET") != TEST_PASS)
            return TEST_FAIL;
        for (unsigned i = 0; i < COUNT; ++i)
            memset(&regs[i].value, 0xa5, sizeof(regs[i].value));
        if (mshv_expect_ioctl(f->vp, MSHV_GET_VP_REGISTERS, &args,
                                "GET register encodings", 0) != TEST_PASS)
            return TEST_FAIL;
        for (unsigned i = 0; i < COUNT; ++i)
            actual[i] = regs[i].value;
        if (check_values(names, expected, actual, COUNT, "compatibility GET") != TEST_PASS)
            return TEST_FAIL;
    }
    return TEST_PASS;
}

REGISTER_MSHV_TEST(TL0001, register_values,
                   "Scalar zero extension and full XMM values",
                   TLFS_SPEC_V6_0B, "7.8");
