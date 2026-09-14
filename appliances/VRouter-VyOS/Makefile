PACKAGE := one-vyos-vrouter
VERSION ?= 0.2.0
RELEASE ?= 1

.PHONY: test deb context-deb deb-all clean

test:
	pytest -q

deb:
	VERSION=$(VERSION) RELEASE=$(RELEASE) ./packaging/build-deb.sh

context-deb:
	../../context-linux/build-vyos-deb.sh
	../../context-linux/tests/test-vyos-package.sh ../../context-linux/out/one-context-vyos_7.4.0-0.deb

deb-all: deb context-deb

clean:
	rm -rf out .pytest_cache **/__pycache__
