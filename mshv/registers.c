/* SPDX-License-Identifier: Apache-2.0 */
#include <errno.h>
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

static test_result_t single(struct mshv_fixture *f)
{
    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;
    const uint64_t values[] = {0, UINT64_MAX, 0x8000000000000001ULL,
                               0x0123456789abcdefULL};
    for (unsigned i = 0; i < sizeof(values) / sizeof(values[0]); ++i)
        if (mshv_roundtrip(f, 1, values[i]) != TEST_PASS)
            return TEST_FAIL;
    return TEST_PASS;
}

static test_result_t batch(struct mshv_fixture *f)
{
    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_roundtrip(f, 4, 0x0123456789abcdefULL) != TEST_PASS)
        return TEST_FAIL;
    return mshv_roundtrip(f, 4, 0xfedcba9876543210ULL);
}

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

REGISTER_MSHV_TEST(MR001, single, "single RAX roundtrips including all bits set");
REGISTER_MSHV_TEST(MR002, batch, "four-register GPR batches with distinct exact values");
REGISTER_MSHV_TEST(MR003, negative, "exact EINVAL/EFAULT checks, each followed by a valid roundtrip");
