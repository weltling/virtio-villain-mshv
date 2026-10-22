/* SPDX-License-Identifier: Apache-2.0 */
/*
 * MR002 - Exact batches of general purpose registers (GPRs).
 *
 * UAPI: MSHV_SET_VP_REGISTERS and MSHV_GET_VP_REGISTERS.
 *
 * Create a partition and virtual processor (VP). Set/get RAX, RCX, RDX and RBX
 * together, requiring four distinct exact 64-bit values. Repeat with another
 * seed to verify replacement. Every IOCTL must return zero.
 * Only valid batches are submitted, so this makes no atomicity claim for
 * mixed-validity requests.
 */
#include "mshv/test.h"

static test_result_t batch(struct mshv_fixture *f)
{
    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_roundtrip(f, 4, 0x0123456789abcdefULL) != TEST_PASS)
        return TEST_FAIL;
    return mshv_roundtrip(f, 4, 0xfedcba9876543210ULL);
}

REGISTER_MSHV_TEST(MR002, batch, "four-register GPR batches with distinct exact values");
