/* SPDX-License-Identifier: Apache-2.0 */
/*
 * MR003 - Exact register errors followed by valid operations.
 *
 * UAPI: MSHV_GET_VP_REGISTERS and MSHV_SET_VP_REGISTERS validation errors.
 *
 * Create a partition and virtual processor (VP), then require:
 *
 * Operation  Invalid input                        Return  errno
 * GET, SET   count 129, above the limit of 128      -1      EINVAL
 * GET, SET   NULL top-level IOCTL argument         -1      EFAULT
 * GET, SET   count one with NULL register array    -1      EFAULT
 * SET        HV_REGISTER_EXPLICIT_SUSPEND          -1      EINVAL
 * SET        HV_REGISTER_INTERCEPT_SUSPEND         -1      EINVAL
 *
 * Count 129 is rejected before any array copy, so one backing entry suffices.
 * After each of the eight rejections, require a valid exact RAX roundtrip.
 * This checks continued usability without assuming atomicity or rollback.
 */
#include <errno.h>
#include "lib/mshv.h"

static test_result_t negative(struct mshv_fixture *f)
{
    struct hv_register_assoc reg = {0};
    struct mshv_vp_registers args = {.count = 1, .regs = &reg};
    const unsigned long requests[] = {MSHV_GET_VP_REGISTERS, MSHV_SET_VP_REGISTERS};
    const char *names[] = {"GET", "SET"};
    char operation[120];

    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;
    for (unsigned i = 0; i < 2; ++i) {
        args.count = MSHV_VP_MAX_REGISTERS + 1;
        snprintf(operation, sizeof(operation), "%s count=129", names[i]);
        if (mshv_expect_ioctl(f->vp, requests[i], &args, operation, EINVAL) != TEST_PASS ||
            mshv_roundtrip(f, 1, 0x1111222233334444ULL + i) != TEST_PASS)
            return TEST_FAIL;
        snprintf(operation, sizeof(operation), "%s NULL ioctl argument", names[i]);
        if (mshv_expect_ioctl(f->vp, requests[i], NULL, operation, EFAULT) != TEST_PASS ||
            mshv_roundtrip(f, 1, 0x5555666677778888ULL + i) != TEST_PASS)
            return TEST_FAIL;
        args.count = 1;
        args.regs = NULL;
        snprintf(operation, sizeof(operation), "%s count=1 NULL register array", names[i]);
        if (mshv_expect_ioctl(f->vp, requests[i], &args, operation, EFAULT) != TEST_PASS ||
            mshv_roundtrip(f, 1, 0x9999aaaabbbbccccULL + i) != TEST_PASS)
            return TEST_FAIL;
        args.regs = &reg;
    }
    const uint32_t forbidden[] = {VV_EXPLICIT_SUSPEND, VV_INTERCEPT_SUSPEND};
    for (unsigned i = 0; i < 2; ++i) {
        reg.name = forbidden[i];
        snprintf(operation, sizeof(operation), "SET forbidden suspend register 0x%x", reg.name);
        if (mshv_expect_ioctl(f->vp, MSHV_SET_VP_REGISTERS, &args,
                              operation, EINVAL) != TEST_PASS ||
            mshv_roundtrip(f, 1, 0xdeadbeef12345678ULL + i) != TEST_PASS)
            return TEST_FAIL;
    }
    return TEST_PASS;
}

REGISTER_MSHV_TEST(MR003, negative, "Exact EINVAL/EFAULT checks, each followed by a valid roundtrip");
