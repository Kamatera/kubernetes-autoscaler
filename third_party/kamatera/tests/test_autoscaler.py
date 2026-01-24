import os
import time
import base64
import subprocess
from textwrap import dedent
import json
import contextlib

from ruamel.yaml import YAML

from kamatera_rke2_kubernetes_terraform_example_tests import setup, util, destroy, k8s_demo_app

yaml = YAML(typ='safe', pure=True)


POWER_OFF_ON_SCALE_DOWN = os.getenv("POWER_OFF_ON_SCALE_DOWN") == "yes"
POWER_ON_ON_SCALE_UP = os.getenv("POWER_ON_ON_SCALE_UP") == "yes"


def get_k8s_tfvars():
    return setup.K8STfvarsConfig(
        ca_rbac_url='https://raw.githubusercontent.com/Kamatera/kubernetes-autoscaler/refs/heads/kamatera-cluster-autoscaler/cluster-autoscaler/cloudprovider/kamatera/examples/rbac.yaml',
        ca_image='gcr.io/k8s-staging-autoscaling/cluster-autoscaler-amd64:dev',
        ca_replicas=0,
        ca_extra_args=[],
        ca_nodegroup_configs={
            "autoscaler": dedent('''
                min-size = 1
                max-size = 3
                cpu = 2B
                ram = 2048
                disk = size=20
                template-label = "kubernetes.io/os=linux"
                template-label = "role=autoscaler"
            '''),
        },
        ca_nodegroup_rke2_extra_config={
            "autoscaler": dedent('''
                node-label:
                  - role=autoscaler
            ''')
        },
    )


def get_server_status(name):
    res = destroy.cloudcli("server", "info", "--name", name, "--format", "json", run=True, capture_output=True)
    if res.returncode == 0:
        servers = json.loads(res.stdout)
        assert len(servers) == 1
        return "power_on" if servers[0]["power"] == "on" else "power_off"
    elif 'No servers found' in res.stdout:
        return "not_found"
    else:
        raise Exception(f"Failed to get server status\n{res.stdout}\n{res.stderr}")


@contextlib.contextmanager
def print_wrapper():
    print('~'*30)
    try:
        yield
    finally:
        print('~'*30)


def print_function(*args):
    txt = " ".join(str(a) for a in args)
    for line in txt.splitlines():
        print(f"~~~~~ {line}")


def count_at_least(actual, expected):
    a_total, a_ready = actual
    e_total, e_ready = expected
    return a_total >= e_total and a_ready >= e_ready


def ensure_stability_nodes_at_least(expected_nodes, expected_pods, iterations=10, total_iterations=30):
    print_function(f'Ensuring cluster stability')
    print_function(f'expected_nodes at least {expected_nodes}')
    print_function(f'expected_pods={expected_pods}')
    stable_iterations = 0
    for i in range(total_iterations):
        print_function(f'iteration {i + 1}/{total_iterations} (stable iterations: {stable_iterations}/{iterations})...')
        if stable_iterations + (total_iterations - i) < iterations:
            print_function('Not enough iterations left to reach stability, failing')
            break
        time.sleep(60)
        actual_nodes = util.kubectl_node_count()
        if not count_at_least(actual_nodes, expected_nodes):
            util.kubectl("get", "nodes")
            print_function(f'unexpected node count: {actual_nodes}, expected at least: {expected_nodes}')
            stable_iterations = 0
            continue
        actual_pods = util.kubectl_pods_count("demo")
        if actual_pods != expected_pods:
            util.kubectl("get", "pods", "-n", "demo")
            print_function(f'unexpected pod count: {actual_pods}, expected: {expected_pods}')
            stable_iterations = 0
            continue
        stable_iterations += 1
        if stable_iterations >= iterations:
            break
    assert stable_iterations >= iterations, f"cluster unstable"
    print_function('Cluster is stable')


def test():
    use_existing_name_prefix = os.getenv("USE_EXISTING_NAME_PREFIX")
    name_prefix = use_existing_name_prefix or setup.generate_name_prefix()
    print(f'name_prefix="{name_prefix}"')
    k8s_version = os.getenv("K8S_VERSION") or "1.35"
    datacenter_id = "US-NY2"
    with_bastion = False
    keep_cluster = os.getenv("KEEP_CLUSTER") == "yes"
    ca_p = None
    try:
        if use_existing_name_prefix:
            util.kubectl("delete", "namespace", "demo", "--ignore-not-found", "--wait")
            destroy.cloudcli("server", "terminate", "--force", "--name", f"{name_prefix}-autoscaler-.*", "--wait", run=True)
            util.kubectl("delete", "nodes", "-l", "role=autoscaler", "--wait")
        else:
            setup.main(
                name_prefix=name_prefix,
                k8s_version=k8s_version,
                datacenter_id=datacenter_id,
                with_bastion=with_bastion,
                k8s_tfvars_config=get_k8s_tfvars()
            )
        util.wait_for(
            "deployment of demo_app",
            lambda: util.kubectl("apply", "-f", "demo_app.yaml", cwd=os.path.dirname(__file__)) or True,
            retry_on_exception=True
        )
        util.wait_for(
            "2 pods total but none running (no autoscaler yet)",
            lambda: util.kubectl_pods_count("demo") == (2,0),
            progress=lambda: util.kubectl("get", "pods", "-n", "demo")
        )
        util.kubectl(
            "apply", "-f", "rbac.yaml",
            cwd=os.path.join(os.path.dirname(__file__), '..', '..', '..', 'cluster-autoscaler', 'cloudprovider', 'kamatera', 'examples')
        )
        token = util.kubectl(
            "create", "token", "cluster-autoscaler", "-n", "kube-system", "--duration", "24h", parse_json=True
        )["status"]["token"]
        with open(util.get_kubeconfig()) as f:
            kubeconfig = yaml.load(f)
        kubeconfig["users"] = [
            {
                "name": "cluster-autoscaler",
                "user": {
                    "token": token
                }
            }
        ]
        kubeconfig["contexts"][0]["context"]["user"] = "cluster-autoscaler"
        ca_kubeconfig = os.path.join(os.path.dirname(__file__), ".kubeconfig")
        with open(ca_kubeconfig, "w") as f:
            yaml.dump(kubeconfig, f)
        cloudconfig = base64.b64decode(util.kubectl("get", "secret", "-n", "kube-system", "cluster-autoscaler-kamatera", parse_json=True)["data"]["cloud-config"]).decode()
        global_configs = []
        if POWER_OFF_ON_SCALE_DOWN:
            global_configs.append("poweroff-on-scale-down = true")
        if POWER_ON_ON_SCALE_UP:
            global_configs.append("poweron-on-scale-up = true")
        cloudconfig = cloudconfig.replace("[global]", "[global]\n" + "\n".join(global_configs))
        with open(os.path.join(os.path.dirname(__file__), ".cloud-config"), "w") as f:
            f.write(cloudconfig)
        ca_args = [
            "../../../cluster-autoscaler/cluster-autoscaler-amd64",
            "--cloud-provider", "kamatera",
            "--cloud-config", "./.cloud-config",
            "--v", "4",
            "--logtostderr",
            "--namespace", "kube-system",
            "--kubeconfig", ca_kubeconfig,
            "--cordon-node-before-terminating",
            # we set low thresholds for faster testing
            "--scale-down-unneeded-time=5m",
            "--initial-node-group-backoff-duration=2m",
            "--max-node-group-backoff-duration=3m",
            "--node-group-backoff-reset-timeout=6m",
            "--provisioning-request-max-backoff-time=6m",
            "--scale-down-delay-after-add=2m",
            "--scale-down-delay-after-failure=2m",
            "--scale-down-unready-time=5m",
        ]
        print("Starting cluster-autoscaler:", " ".join(ca_args))
        ca_p = subprocess.Popen(
            ca_args, cwd=os.path.dirname(__file__),
        )

        # from this point onwards we need to clearly isolate prints so they stand out from the CA logs
        def wait_for(*args, **kwargs):
            with print_wrapper():
                return util.wait_for(*args, print_function=print_function, **kwargs)

        def ensure_stability(*args, **kwargs):
            with print_wrapper():
                return k8s_demo_app.ensure_stability(*args, print_function=print_function, **kwargs)

        wait_for(
            f"3 nodes to be ready",
            lambda: util.kubectl_node_count() == (3, 3),
            progress=lambda: util.kubectl("get", "nodes"),
            retry_on_exception=True,
            timeout_seconds=3600,  # servers may take a while to create
        )
        node_names = {node["metadata"]["name"] for node in util.kubectl("get", "nodes", parse_json=True)["items"]}
        node_names.remove("controlplane1")
        assert len(node_names) == 2 and all(name.startswith(f"{name_prefix}-autoscaler-") for name in node_names), node_names
        wait_for(
            "2 pods total and running (after autoscaler adds nodes)",
            lambda: util.kubectl_pods_count("demo") == (2, 2),
            progress=lambda: util.kubectl("get", "pods", "-n", "demo"),
        )
        pods = util.kubectl("get", "pods", "-n", "demo", parse_json=True)["items"]
        assert len(pods) == 2 and all(pod["spec"]["nodeName"].startswith(f"{name_prefix}-autoscaler-") for pod in pods), pods
        ensure_stability(
            (3, 3),
            (2, 2)
        )
        with print_wrapper():
            util.kubectl("scale", "deployment", "demo", "-n", "demo", "--replicas=0")
        wait_for(
            "all demo pods terminated",
            lambda: util.kubectl_pods_count("demo") == (0, 0),
            progress=lambda: util.kubectl("get", "pods", "-n", "demo"),
        )
        wait_for(
            f"3 total nodes, 2 ready nodes (after autoscaler removes unneeded nodes)",
            lambda: util.kubectl_node_count() == (3, 2),
            progress=lambda: util.kubectl("get", "nodes"),
        )
        notready_node_names = []
        for node in util.kubectl("get", "nodes", parse_json=True)["items"]:
            for condition in node.get("status", {}).get("conditions", []):
                if condition.get("type") == "Ready" and condition.get("status") != "True":
                    notready_node_names.append(node["metadata"]["name"])
        assert len(notready_node_names) == 1
        scaled_down_node_name = notready_node_names[0]
        expected_status = "power_off" if POWER_OFF_ON_SCALE_DOWN else "not_found"
        wait_for(
            f'scaled down node to be {expected_status}',
            lambda: get_server_status(scaled_down_node_name) == expected_status,
        )
        with print_wrapper():
            util.kubectl("scale", "deployment", "demo", "-n", "demo", "--replicas=2")
        wait_for(
            f"at least 3 nodes total and 3 ready (after autoscaler powers on or creates a new node)",
            lambda: count_at_least(util.kubectl_node_count(), (3, 3)),
            progress=lambda: util.kubectl("get", "nodes"),
        )
        wait_for(
            "2 pods total and running (after autoscaler scales back up)",
            lambda: util.kubectl_pods_count("demo") == (2, 2),
            progress=lambda: util.kubectl("get", "pods", "-n", "demo"),
        )
        ensure_stability_nodes_at_least((3, 3), (2, 2))
        with print_wrapper():
            print_function("Autoscaler Test Completed Successfully")
    except:
        if ca_p:
            ca_p.terminate()
            ca_p.wait()
            if ca_p.stdout:
                for line in ca_p.stdout:
                    print(line.decode().rstrip())
        util.kubectl("get", "nodes")
        util.kubectl("get", "pods", "-n", "demo")
        print(f'name_prefix="{name_prefix}"')
        raise
    else:
        if ca_p:
            ca_p.terminate()
            ca_p.wait()
        if keep_cluster:
            print(f'name_prefix="{name_prefix}"')
        else:
            destroy.main(
                name_prefix=name_prefix,
                datacenter_id=datacenter_id,
            )
