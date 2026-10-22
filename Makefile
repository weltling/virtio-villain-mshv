# SPDX-License-Identifier: Apache-2.0
CC = gcc
CFLAGS ?= -static -O2 -Wall -Wextra -Werror
LDFLAGS ?= -static
TARGET ?= target
MSHV_SOURCE ?= $(HOME)/linux
VV_ROOT ?= $(HOME)/virtio-villain
SRCS = bin/mshv.c mshv/lifecycle.c mshv/registers.c

.DEFAULT_GOAL := mshv-initramfs

contract:
	python3 mshv/contract.py --source "$(MSHV_SOURCE)" --output "$(TARGET)/mshv/contract.h"

mshv mshv-initramfs: contract
	$(MAKE) -C "$(VV_ROOT)" appliance-initramfs CC="$(CC)" \
	  APPLIANCE_SRCS="$(addprefix $(CURDIR)/,$(SRCS))" \
	  APPLIANCE_TARGET="$(abspath $(TARGET))/mshv" \
	  APPLIANCE_CPPFLAGS="-I$(CURDIR) -I$(abspath $(TARGET))/mshv" \
	  CFLAGS="$(CFLAGS)" LDFLAGS="$(LDFLAGS)"

kernel:
	"$(VV_ROOT)/build-kernel" --source "$(MSHV_SOURCE)" \
	  --config "$(MSHV_SOURCE)/Microsoft/configs/x86/mshv_defconfig" \
	  --output "$(abspath $(TARGET))/kernel-microsoft" \
	  --cache-dir "$(abspath $(TARGET))/kernel-cache" --offline --jobs "$$(nproc)"

selftest:
	python3 -m unittest discover -s selftest -p 'test_*.py'

lint:
	python3 -m flake8 run-mshv launch-nested suite.py mshv selftest

.PHONY: contract mshv mshv-initramfs kernel selftest lint
