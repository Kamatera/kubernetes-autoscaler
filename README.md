# Kamatera Kubernetes Autoscaler

This is a fork of kubernetes/autoscaler with changes related to Kamatera Cloud Provider.

## Docker Images

Docker images are built for every Kubernetes minor version:

* `ghcr.io/kamatera/kubernetes-autoscaler:kamatera-cluster-autoscaler-release-<KUBERNETES_MINOR_VERSION>`
* e.g.: `ghcr.io/kamatera/kubernetes-autoscaler:kamatera-cluster-autoscaler-release-1.32`

For a specific release the image is also tagged with the git sha of the commit:

* `ghcr.io/kamatera/kubernetes-autoscaler:kamatera-cluster-autoscaler-release-<KUBERNETES_MINOR_VERSION>-<GIT_SHA>`

## Branches

All Kamatera-specific changes are in branches prefixed with `kamatera-`:

* `kamatera-cluster-autoscaler`: Tracks the main autoscaler repository, focus on the cluster autoscaler component.
* `kamatera-cluster-autoscaler-release-X.Y`: Release branches for the Kamatera cluster autoscaler

Changes from upstream are rebased onto these branches.

`master` branch is used to track changes pending merge to upstream, there will be a PR pending on `kubernetes/autoscaler` repo tracking it. 

## Cluster Autoscaler

See [cluster-autoscaler/cloudprovider/kamatera/README.md](cluster-autoscaler/cloudprovider/kamatera/README.md)
