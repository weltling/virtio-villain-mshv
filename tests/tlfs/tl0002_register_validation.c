/* SPDX-License-Identifier: Apache-2.0 */
/*
 * TL0002: Read only registers and architectural register bit validation.
 *
 * TLFS 6.0b section 7.10.1 requires fixed and reserved bits to be valid
 * and forbids modifying read only registers through HvSetVpRegisters.
 * Requires x86-64 VP index access and parent register access.
 * Each rejected write has one element. No batch rollback is assumed.
 */
#include <inttypes.h>

#include "lib/mshv.h"

static test_result_t register_validation(struct mshv_fixture *f)
{
    const uint32_t names[] = {VV_VP_INDEX, VV_RFLAGS};
    union hv_register_value original[2];

    if (mshv_create_configured(f, VV_MSHV_PARTITION_FLAGS_NONE, VV_TLFS_BASIC_FEATURES) != TEST_PASS ||
        mshv_get_registers(f->vp, 0, names, original, 2) != TEST_PASS)
        return TEST_FAIL;
    if (!(original[1].reg64 & UINT64_C(2)) || (original[1].reg64 & UINT64_C(8)))
        TFAIL("initial RFLAGS: expected bit 1 set and bit 3 clear, actual 0x%" PRIx64,
              original[1].reg64);

    const struct hv_register_assoc invalid[] = {
        {.name = VV_VP_INDEX, .value.reg64 = 1},
        {.name = VV_RFLAGS, .value.reg64 = original[1].reg64 & ~UINT64_C(2)},
        {.name = VV_RFLAGS, .value.reg64 = original[1].reg64 | UINT64_C(8)},
    };
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
        struct {
            struct hv_vp_register_header header;
            struct hv_register_assoc reg;
        } input = {.reg = invalid[i]};
        struct mshv_root_hvcall args = {
            .code = HVCALL_SET_VP_REGISTERS,
            .reps = 1,
            .in_sz = sizeof(input),
            .in_ptr = (uintptr_t)&input,
        };
        char operation[96];
        snprintf(operation, sizeof(operation), "reject register 0x%x value=0x%" PRIx64,
                 invalid[i].name, invalid[i].value.reg64);
        if (mshv_expect_hvcall(f->vp, &args, operation, VV_HVCALL_REJECTED) != TEST_PASS) {
            union hv_register_value readback;
            if (mshv_get_registers(f->vp, 0, &invalid[i].name, &readback, 1) == TEST_PASS)
                printf("mshv-register unexpected write readback name=0x%x high=0x%" PRIx64
                       " low=0x%" PRIx64 "\n", invalid[i].name,
                       readback.words[1], readback.words[0]);
            return TEST_FAIL;
        }
        union hv_register_value actual;
        unsigned original_index = i == 0 ? 0 : 1;
        if (mshv_get_registers(f->vp, 0, &names[original_index], &actual, 1) != TEST_PASS)
            return TEST_FAIL;
        if (actual.words[0] != original[original_index].words[0] ||
            actual.words[1] != original[original_index].words[1])
            TFAIL("rejected register 0x%x changed: expected 0x%" PRIx64
                  ", actual 0x%" PRIx64, invalid[i].name,
                  original[original_index].reg64, actual.reg64);
        if (mshv_roundtrip(f, 4, VV_GPR_SEED_FORBIDDEN_REGISTER + i) != TEST_PASS)
            return TEST_FAIL;
    }
    return TEST_PASS;
}

REGISTER_MSHV_TEST(TL0002, register_validation,
                   "Read only and fixed register bit restrictions",
                   TLFS_SPEC_V6_0B, "7.10.1");
