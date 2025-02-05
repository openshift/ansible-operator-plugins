// Copyright 2021 The Operator-SDK Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package handler

import (
	"context"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	dto "github.com/prometheus/client_model/go"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllertest"
	"sigs.k8s.io/controller-runtime/pkg/event"
	"sigs.k8s.io/controller-runtime/pkg/metrics"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	"k8s.io/client-go/util/workqueue"
)

var _ = Describe("LoggingEnqueueRequestForObject", func() {
	var q workqueue.TypedRateLimitingInterface[reconcile.Request]
	var instance LoggingEnqueueRequestForObject
	var pod *corev1.Pod
	var ctx = context.TODO()

	BeforeEach(func() {
		logBuffer.Reset()
		q = &controllertest.TypedQueue[reconcile.Request]{TypedInterface: workqueue.NewTyped[reconcile.Request]()}
		instance = LoggingEnqueueRequestForObject{}
		pod = &corev1.Pod{
			TypeMeta: metav1.TypeMeta{
				Kind:       "Pod",
				APIVersion: "v1",
			},
			ObjectMeta: metav1.ObjectMeta{
				Namespace:         "biznamespace",
				Name:              "bizname",
				CreationTimestamp: metav1.Now(),
			},
		}
	})
	Describe("Create", func() {
		It("should emit a log, enqueue a request & emit a metric on a CreateEvent", func() {
			evt := event.CreateEvent{
				Object: pod,
			}

			// test the create
			logBuffer.Reset()
			instance.Create(ctx, evt, q)
			Expect(logBuffer.String()).To(MatchRegexp(
				`ansible.handler.*Create.*/v1.*Pod.*bizname.*biznamespace`,
			))

			// verify workqueue
			Expect(q.Len()).To(Equal(1))
			i, _ := q.Get()
			Expect(i).To(Equal(reconcile.Request{
				NamespacedName: types.NamespacedName{
					Namespace: pod.Namespace,
					Name:      pod.Name,
				},
			}))

			// verify metrics
			rawGauges, err := metrics.Registry.Gather()
			Expect(err).NotTo(HaveOccurred())
			gauges := filterGauges(rawGauges)
			Expect(gauges).To(HaveLen(1))
			assertMetrics(gauges[0], 1, []*corev1.Pod{pod})
		})
	})

	Describe("Delete", func() {
		Context("when a gauge already exists", func() {
			BeforeEach(func() {
				evt := event.CreateEvent{
					Object: pod,
				}
				logBuffer.Reset()
				instance.Create(ctx, evt, q)
				Expect(logBuffer.String()).To(MatchRegexp(
					`ansible.handler.*Create.*/v1.*Pod.*bizname.*biznamespace`,
				))
				Expect(q.Len()).To(Equal(1))
			})
			It("should emit a log, enqueue a request & remove the metric on a DeleteEvent", func() {
				evt := event.DeleteEvent{
					Object: pod,
				}

				logBuffer.Reset()
				// test the delete
				instance.Delete(ctx, evt, q)
				Expect(logBuffer.String()).To(MatchRegexp(
					`ansible.handler.*Delete.*/v1.*Pod.*bizname.*biznamespace`,
				))

				// verify workqueue
				Expect(q.Len()).To(Equal(1))
				i, _ := q.Get()
				Expect(i).To(Equal(reconcile.Request{
					NamespacedName: types.NamespacedName{
						Namespace: pod.Namespace,
						Name:      pod.Name,
					},
				}))

				// verify metrics
				rawGauges, err := metrics.Registry.Gather()
				Expect(err).NotTo(HaveOccurred())
				gauges := filterGauges(rawGauges)
				Expect(gauges).To(BeEmpty())
			})
		})
		Context("when a gauge does not exist", func() {
			It("should emit a log, enqueue a request & there should be no new metric on a DeleteEvent", func() {
				evt := event.DeleteEvent{
					Object: pod,
				}

				logBuffer.Reset()
				// test the delete
				instance.Delete(ctx, evt, q)
				Expect(logBuffer.String()).To(MatchRegexp(
					`ansible.handler.*Delete.*/v1.*Pod.*bizname.*biznamespace`,
				))

				// verify workqueue
				Expect(q.Len()).To(Equal(1))
				i, _ := q.Get()
				Expect(i).To(Equal(reconcile.Request{
					NamespacedName: types.NamespacedName{
						Namespace: pod.Namespace,
						Name:      pod.Name,
					},
				}))

				// verify metrics
				rawGauges, err := metrics.Registry.Gather()
				Expect(err).NotTo(HaveOccurred())
				gauges := filterGauges(rawGauges)
				Expect(gauges).To(BeEmpty())
			})
		})

	})

	Describe("Update", func() {
		It("should emit a log and enqueue a request in case of UpdateEvent", func() {
			newpod := &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{
					Namespace: "baznamespace",
					Name:      "bazname",
				},
			}
			evt := event.UpdateEvent{
				ObjectOld: pod,
				ObjectNew: newpod,
			}

			logBuffer.Reset()
			// test the update
			instance.Update(ctx, evt, q)
			Expect(logBuffer.String()).To(MatchRegexp(
				`ansible.handler.*Update.*/v1.*Pod.*bizname.*biznamespace`,
			))

			// verify workqueue
			Expect(q.Len()).To(Equal(1))
			i, _ := q.Get()
			Expect(i).To(Equal(reconcile.Request{
				NamespacedName: types.NamespacedName{
					Namespace: newpod.Namespace,
					Name:      newpod.Name,
				},
			}))

			// verify metrics
			rawGauges, err := metrics.Registry.Gather()
			Expect(err).NotTo(HaveOccurred())
			gauges := filterGauges(rawGauges)
			Expect(gauges).To(HaveLen(1))
			assertMetrics(gauges[0], 2, []*corev1.Pod{newpod, pod})
		})
	})
})

func assertMetrics(gauge *dto.MetricFamily, count int, pods []*corev1.Pod) {
	Expect(gauge.Metric).To(HaveLen(count))
	for i := 0; i < count; i++ {
		Expect(*gauge.Metric[i].Gauge.Value).To(Equal(float64(pods[i].GetObjectMeta().GetCreationTimestamp().UTC().Unix())))

		for _, l := range gauge.Metric[i].Label {
			if l.Name != nil {
				switch *l.Name {
				case "name":
					Expect(l.Value).To(HaveValue(Equal(pods[i].GetObjectMeta().GetName())))
				case "namespace":
					Expect(l.Value).To(HaveValue(Equal(pods[i].GetObjectMeta().GetNamespace())))
				case "group":
					Expect(l.Value).To(HaveValue(Equal(pods[i].GetObjectKind().GroupVersionKind().Group)))
				case "version":
					Expect(l.Value).To(HaveValue(Equal(pods[i].GetObjectKind().GroupVersionKind().Version)))
				case "kind":
					Expect(l.Value).To(HaveValue(Equal(pods[i].GetObjectKind().GroupVersionKind().Kind)))
				}
			}
		}
	}
}

func filterGauges(gauges []*dto.MetricFamily) []*dto.MetricFamily {
	var filteredGauges []*dto.MetricFamily
	for _, gauge := range gauges {
		if *gauge.Name != "rest_client_requests_total" {
			filteredGauges = append(filteredGauges, gauge)
		}
	}
	return filteredGauges
}
