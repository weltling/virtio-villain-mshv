/* SPDX-License-Identifier: Apache-2.0 */
/*
 * ML0015 - Interrupt and eventfd registration parameter boundary checks.
 *
 * UAPI: MSHV_IRQFD, MSHV_IOEVENTFD.
 *
 * Verify that IRQFD and IOEVENTFD reject invalid flags with EINVAL,
 * invalid file descriptors with EBADF, and NULL arguments with EFAULT.
 *
 * Following all rejections, confirm that general purpose registers remain
 * undamaged.
 */
#include <errno.h>
#include <inttypes.h>
#include <string.h>

#include "lib/mshv.h"

static test_result_t irq_eventfd(struct mshv_fixture *f)
{
    struct mshv_user_irqfd bad_irqfd_flags = {
        .fd = 0,
        .resamplefd = -1,
        .gsi = 1,
        .flags = 0xffff,
    };
    struct mshv_user_irqfd bad_irqfd_fd = {
        .fd = -1,
        .resamplefd = -1,
        .gsi = 1,
        .flags = 0,
    };
    struct mshv_user_ioeventfd bad_ioeventfd_flags = {
        .datamatch = 0,
        .addr = 0x1000,
        .len = 4,
        .fd = 0,
        .flags = 0xffff,
    };
    struct mshv_user_ioeventfd bad_ioeventfd_len = {
        .datamatch = 0,
        .addr = 0x1000,
        .len = 3,
        .fd = 0,
        .flags = 0,
    };

    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;

    /* NULL arguments must return EFAULT */
    if (mshv_expect_ioctl(f->partition, MSHV_IRQFD, NULL,
                          "MSHV_IRQFD NULL", EFAULT) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->partition, MSHV_IOEVENTFD, NULL,
                          "MSHV_IOEVENTFD NULL", EFAULT) != TEST_PASS)
        return TEST_FAIL;

    /* Invalid flags must return EINVAL */
    if (mshv_expect_ioctl(f->partition, MSHV_IRQFD, &bad_irqfd_flags,
                          "MSHV_IRQFD bad flags", EINVAL) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->partition, MSHV_IOEVENTFD, &bad_ioeventfd_flags,
                          "MSHV_IOEVENTFD bad flags", EINVAL) != TEST_PASS)
        return TEST_FAIL;

    /* Bad file descriptor must return EBADF */
    if (mshv_expect_ioctl(f->partition, MSHV_IRQFD, &bad_irqfd_fd,
                          "MSHV_IRQFD bad fd", EBADF) != TEST_PASS)
        return TEST_FAIL;

    /* Invalid access length must return EINVAL */
    if (mshv_expect_ioctl(f->partition, MSHV_IOEVENTFD, &bad_ioeventfd_len,
                          "MSHV_IOEVENTFD bad len", EINVAL) != TEST_PASS)
        return TEST_FAIL;

    return mshv_roundtrip(f, 4, VV_GPR_SEED_IRQ_EVENTFD);
}

REGISTER_MSHV_TEST(ML0015, irq_eventfd,
                   "Interrupt and eventfd registration parameter boundary checks", "", "");
