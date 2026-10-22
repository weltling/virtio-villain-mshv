/* SPDX-License-Identifier: Apache-2.0 */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "lib/mshv.h"

static int types[4096], indices[4096], next_fd = 20, open_fds;
static int vp_created[2], references, calls, fail_at, corrupt_read, close_failure;
static uint64_t values[2][4];

static int allocate(int type, int index)
{
    assert(next_fd < 4096);
    int fd = next_fd++;
    types[fd] = type;
    indices[fd] = index;
    ++open_fds;
    return fd;
}

int __wrap_open(const char *path, int flags, ...)
{
    assert(!strcmp(path, "/dev/mshv"));
    assert(flags == (O_RDWR | O_CLOEXEC));
    return allocate(1, 0);
}

int __wrap_fcntl(int fd, int command, ...)
{
    assert(types[fd] && command == F_GETFD);
    return FD_CLOEXEC;
}

int __wrap_close(int fd)
{
    assert(types[fd]);
    if (types[fd] != 1 && --references == 0) {
        memset(vp_created, 0, sizeof(vp_created));
        memset(values, 0, sizeof(values));
    }
    types[fd] = 0;
    --open_fds;
    if (close_failure) {
        close_failure = 0;
        errno = EINTR;
        return -1;
    }
    return 0;
}

static int reject(int error)
{
    errno = error;
    return -1;
}

int __wrap_ioctl(int fd, unsigned long request, ...)
{
    va_list ap;
    va_start(ap, request);
    void *arg = va_arg(ap, void *);
    va_end(ap);
    assert(types[fd]);
    if (++calls == fail_at)
        return reject(EIO);
    if (types[fd] == 1 && request == MSHV_CREATE_PARTITION) {
        struct mshv_create_partition *args = arg;
        assert(args && args->pt_flags == 0 && args->pt_isolation == 0);
        assert(references == 0);
        ++references;
        return allocate(2, 0);
    }
    if (types[fd] == 2 && request == MSHV_INITIALIZE_PARTITION)
        return 0;
    if (types[fd] == 2 && request == MSHV_CREATE_VP) {
        struct mshv_create_vp *args = arg;
        assert(args && args->vp_index < 2);
        if (vp_created[args->vp_index])
            return reject(EEXIST);
        vp_created[args->vp_index] = 1;
        ++references;
        return allocate(3, args->vp_index);
    }
    assert(types[fd] == 3);
    assert(request == MSHV_GET_VP_REGISTERS || request == MSHV_SET_VP_REGISTERS);
    struct mshv_vp_registers *args = arg;
    if (!args)
        return reject(EFAULT);
    if (args->count > MSHV_VP_MAX_REGISTERS)
        return reject(EINVAL);
    if (!args->regs)
        return reject(EFAULT);
    for (unsigned i = 0; i < args->count; ++i) {
        struct hv_register_assoc *reg = &args->regs[i];
        if (request == MSHV_SET_VP_REGISTERS &&
            (reg->name == VV_EXPLICIT_SUSPEND || reg->name == VV_INTERCEPT_SUSPEND))
            return reject(EINVAL);
        assert(reg->name >= VV_RAX && reg->name <= VV_RBX);
        unsigned n = reg->name - VV_RAX;
        if (request == MSHV_SET_VP_REGISTERS)
            values[indices[fd]][n] = reg->value.reg64;
        else
            reg->value.reg64 = values[indices[fd]][n] ^ corrupt_read;
    }
    return 0;
}

static test_result_t execute(const struct vv_test_entry *test)
{
    struct mshv_fixture f = {.device = -1, .partition = -1, .vp = -1};
    test_result_t result = test->fn(&f);
    if (mshv_cleanup(&f) != TEST_PASS)
        result = TEST_FAIL;
    assert(open_fds == 0 && references == 0);
    return result;
}

int main(void)
{
    const struct vv_test_entry *lifecycle = NULL, *single = NULL, *negative = NULL;
    unsigned count = 0;
    for (const struct vv_test_entry *test = __start_mshv_registry;
         test < __stop_mshv_registry; ++test) {
        assert(execute(test) == TEST_PASS);
        if (!strcmp(test->name, "ML001"))
            lifecycle = test;
        if (!strcmp(test->name, "MR001"))
            single = test;
        if (!strcmp(test->name, "MR003"))
            negative = test;
        ++count;
    }
    assert(count == 7 && lifecycle && single && negative);
    for (int step = 1; step <= 6; ++step) {
        calls = 0;
        fail_at = step;
        assert(execute(lifecycle) == TEST_FAIL);
    }
    fail_at = 0;
    corrupt_read = 1;
    assert(execute(single) == TEST_FAIL);
    corrupt_read = 0;
    close_failure = 1;
    assert(execute(lifecycle) == TEST_FAIL);
    assert(execute(negative) == TEST_PASS);
    puts("mshv mock checks passed");
    return 0;
}
