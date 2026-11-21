"""In-memory fakes for the AWS APIs the aws_ec2 provider calls (service-quotas, autoscaling, cloudformation)."""
import time


class FakeQuotas:
    def __init__(self, spot=0.0, ondemand=0.0, error=None):
        self.values = {"L-3819A6DF": spot, "L-DB2E81BA": ondemand}
        self.error = error
        self.calls = []

    def get_service_quota(self, ServiceCode, QuotaCode):
        self.calls.append((ServiceCode, QuotaCode))
        if self.error:
            raise self.error
        return {"Quota": {"ServiceCode": ServiceCode, "QuotaCode": QuotaCode, "Value": self.values[QuotaCode]}}


class FakeASG:
    def __init__(self, spot_max=2, od_max=1):
        self.groups = {"story-farm-spot-workers": {"AutoScalingGroupName": "story-farm-spot-workers", "MinSize": 0,
                                                   "MaxSize": spot_max, "DesiredCapacity": 0, "Instances": []},
                       "story-farm-ondemand-workers": {"AutoScalingGroupName": "story-farm-ondemand-workers",
                                                       "MinSize": 0, "MaxSize": od_max, "DesiredCapacity": 0,
                                                       "Instances": []}}
        self.activities = {k: [] for k in self.groups}
        self.desired_calls, self.terminated = [], []

    def describe_auto_scaling_groups(self, AutoScalingGroupNames):
        return {"AutoScalingGroups": [self.groups[n] for n in AutoScalingGroupNames if n in self.groups]}

    def describe_scaling_activities(self, AutoScalingGroupName, MaxRecords=10):
        return {"Activities": self.activities[AutoScalingGroupName][:MaxRecords]}

    def set_desired_capacity(self, AutoScalingGroupName, DesiredCapacity, HonorCooldown=False):
        self.desired_calls.append((AutoScalingGroupName, DesiredCapacity))
        self.groups[AutoScalingGroupName]["DesiredCapacity"] = DesiredCapacity

    def terminate_instance_in_auto_scaling_group(self, InstanceId, ShouldDecrementDesiredCapacity):
        self.terminated.append(InstanceId)
        for g in self.groups.values():
            for i in g["Instances"]:
                if i["InstanceId"] == InstanceId:
                    i["LifecycleState"] = "Terminating"
                    if ShouldDecrementDesiredCapacity:
                        g["DesiredCapacity"] -= 1

    # test helpers
    def boot(self, group, iid, itype="g6.xlarge"):
        self.groups[group]["Instances"].append({"InstanceId": iid, "InstanceType": itype,
                                                "LifecycleState": "InService", "HealthStatus": "Healthy"})

    def fail(self, group, msg="Launching a new EC2 instance. Status Reason: We currently do not have sufficient "
                              "g6.xlarge capacity. InsufficientInstanceCapacity"):
        self.activities[group].insert(0, {"StatusCode": "Failed", "StatusMessage": msg, "StartTime": time.time()})


class FakeCfn:
    def describe_stacks(self, StackName):
        return {"Stacks": [{"Outputs": [{"OutputKey": "SpotGroupName", "OutputValue": "story-farm-spot-workers"},
                                        {"OutputKey": "OnDemandGroupName",
                                         "OutputValue": "story-farm-ondemand-workers"}]}]}


def aws_clients(spot=0.0, ondemand=0.0, **kw):
    asg = FakeASG(**kw)
    return {"service-quotas": FakeQuotas(spot, ondemand), "autoscaling": asg, "cloudformation": FakeCfn()}, asg
