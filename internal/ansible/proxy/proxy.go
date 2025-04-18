// Copyright 2018 The Operator-SDK Authors
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

package proxy

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	libhandler "github.com/operator-framework/operator-lib/handler"
	"github.com/operator-framework/operator-lib/predicate"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/client-go/discovery"
	"k8s.io/client-go/rest"
	"sigs.k8s.io/controller-runtime/pkg/cache"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/source"

	"github.com/operator-framework/ansible-operator-plugins/internal/ansible/handler"
	"github.com/operator-framework/ansible-operator-plugins/internal/ansible/proxy/controllermap"
	"github.com/operator-framework/ansible-operator-plugins/internal/ansible/proxy/kubeconfig"
	k8sRequest "github.com/operator-framework/ansible-operator-plugins/internal/ansible/proxy/requestfactory"
)

// This is the default timeout to wait for the cache to respond
// todo(shawn-hurley): Eventually this should be configurable
const cacheEstablishmentTimeout = 6 * time.Second
const AutoSkipCacheREList = "^/api/.*/pods/.*/exec,^/api/.*/pods/.*/attach"

// RequestLogHandler - log the requests that come through the proxy.
func RequestLogHandler(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		// read body
		body, err := io.ReadAll(req.Body)
		if err != nil {
			log.Error(err, "Could not read request body")
		}
		// fix body
		req.Body = io.NopCloser(bytes.NewBuffer(body))
		log.Info("Request Info", "method", req.Method, "uri", req.RequestURI, "body", string(body))
		// Removing the authorization so that the proxy can set the correct authorization.
		req.Header.Del("Authorization")
		h.ServeHTTP(w, req)
	})
}

// HandlerChain will be used for users to pass defined handlers to the proxy.
// The hander chain will be run after InjectingOwnerReference if it is added
// and before the proxy handler.
type HandlerChain func(http.Handler) http.Handler

// Options will be used by the user to specify the desired details
// for the proxy.
type Options struct {
	Address           string
	Port              int
	Handler           HandlerChain
	KubeConfig        *rest.Config
	Scheme            *runtime.Scheme
	Cache             cache.Cache
	RESTMapper        meta.RESTMapper
	ControllerMap     *controllermap.ControllerMap
	WatchedNamespaces map[string]cache.Config
	DisableCache      bool
	OwnerInjection    bool
	LogRequests       bool
}

// Run will start a proxy server in a go routine that returns on the error
// channel if something is not correct on startup. Run will not return until
// the network socket is listening.
func Run(done chan error, o Options) error {
	server, err := newServer("/", o.KubeConfig)
	if err != nil {
		return err
	}
	if o.Handler != nil {
		server.Handler = o.Handler(server.Handler)
	}
	if o.ControllerMap == nil {
		return fmt.Errorf("failed to get controller map from options")
	}
	if o.WatchedNamespaces == nil {
		return fmt.Errorf("failed to get list of watched namespaces from options")
	}

	// Create apiResources and
	discoveryClient, err := discovery.NewDiscoveryClientForConfig(o.KubeConfig)
	if err != nil {
		return err
	}
	resources := &apiResources{
		mu:               &sync.RWMutex{},
		gvkToAPIResource: map[string]metav1.APIResource{},
		discoveryClient:  discoveryClient,
	}

	if o.Cache == nil && !o.DisableCache {
		// Need to initialize cache since we don't have one
		log.Info("Initializing and starting informer cache...")
		informerCache, err := cache.New(o.KubeConfig, cache.Options{})
		if err != nil {
			return err
		}
		ctx, cancel := context.WithCancel(context.TODO())
		go func() {
			if err := informerCache.Start(ctx); err != nil {
				log.Error(err, "Failed to start informer cache")
			}
			defer cancel()
		}()
		log.Info("Waiting for cache to sync...")
		synced := informerCache.WaitForCacheSync(context.TODO())
		if !synced {
			return fmt.Errorf("failed to sync cache")
		}
		log.Info("Cache sync was successful")
		o.Cache = informerCache
	}

	// Remove the authorization header so the proxy can correctly inject the header.
	server.Handler = removeAuthorizationHeader(server.Handler)

	if o.OwnerInjection {
		server.Handler = &injectOwnerReferenceHandler{
			next:              server.Handler,
			cMap:              o.ControllerMap,
			restMapper:        o.RESTMapper,
			scheme:            o.Scheme,
			cache:             o.Cache,
			watchedNamespaces: o.WatchedNamespaces,
			apiResources:      resources,
		}
	} else {
		log.Info("Warning: injection of owner references and dependent watches is turned off")
	}
	if o.LogRequests {
		server.Handler = RequestLogHandler(server.Handler)
	}
	if !o.DisableCache {
		autoSkipCacheRegexp, err := MakeRegexpArray(AutoSkipCacheREList)
		if err != nil {
			log.Error(err, "Failed to parse cache skip regular expression")
		}
		server.Handler = &cacheResponseHandler{
			next:              server.Handler,
			scheme:            o.Scheme,
			informerCache:     o.Cache,
			restMapper:        o.RESTMapper,
			watchedNamespaces: o.WatchedNamespaces,
			cMap:              o.ControllerMap,
			injectOwnerRef:    o.OwnerInjection,
			apiResources:      resources,
			skipPathRegexp:    autoSkipCacheRegexp,
		}
	}

	l, err := server.Listen(o.Address, o.Port)
	if err != nil {
		return err
	}
	go func() {
		log.Info("Starting to serve", "Address", l.Addr().String())
		done <- server.ServeOnListener(l)
	}()
	return nil
}

// Helper function used by cache response and owner injection
func addWatchToController(owner kubeconfig.NamespacedOwnerReference, cMap *controllermap.ControllerMap,
	resource *unstructured.Unstructured, restMapper meta.RESTMapper, cache cache.Cache, scheme *runtime.Scheme, useOwnerRef bool) error {
	dataMapping, err := restMapper.RESTMapping(resource.GroupVersionKind().GroupKind(),
		resource.GroupVersionKind().Version)
	if err != nil {
		m := fmt.Sprintf("Could not get rest mapping for: %v", resource.GroupVersionKind())
		log.Error(err, m)
		return err
	}
	ownerGV, err := schema.ParseGroupVersion(owner.APIVersion)
	if err != nil {
		m := fmt.Sprintf("could not get group version for: %v", owner)
		log.Error(err, m)
		return err
	}
	ownerMapping, err := restMapper.RESTMapping(schema.GroupKind{Kind: owner.Kind, Group: ownerGV.Group},
		ownerGV.Version)
	if err != nil {
		m := fmt.Sprintf("could not get rest mapping for: %v", owner)
		log.Error(err, m)
		return err
	}

	dataNamespaceScoped := dataMapping.Scope.Name() != meta.RESTScopeNameRoot
	contents, ok := cMap.Get(ownerMapping.GroupVersionKind)
	if !ok {
		return errors.New("failed to find controller in map")
	}
	owMap := contents.OwnerWatchMap
	awMap := contents.AnnotationWatchMap
	u := &unstructured.Unstructured{}
	u.SetGroupVersionKind(ownerMapping.GroupVersionKind)

	// Add a watch to controller
	if contents.WatchDependentResources && !contents.Blacklist[resource.GroupVersionKind()] {
		// Store watch in map
		// Use EnqueueRequestForOwner unless user has configured watching cluster scoped resources and we have to
		switch {
		case useOwnerRef:
			_, exists := owMap.Get(resource.GroupVersionKind())
			// If already watching resource no need to add a new watch
			if exists {
				return nil
			}

			owMap.Store(resource.GroupVersionKind())
			log.Info("Watching child resource", "kind", resource.GroupVersionKind(),
				"enqueue_kind", u.GroupVersionKind())
			err := contents.Controller.Watch(source.Kind(cache, client.Object(resource),
				handler.EnqueueRequestForOwnerWithLogging(scheme, restMapper, u),
				predicate.DependentPredicate{}))
			// Store watch in map
			if err != nil {
				log.Error(err, "Failed to watch child resource",
					"kind", resource.GroupVersionKind(), "enqueue_kind", u.GroupVersionKind())
				return err
			}
		case (!useOwnerRef && dataNamespaceScoped) || contents.WatchClusterScopedResources:
			_, exists := awMap.Get(resource.GroupVersionKind())
			// If already watching resource no need to add a new watch
			if exists {
				return nil
			}
			awMap.Store(resource.GroupVersionKind())
			ownerGK := schema.GroupKind{
				Kind:  owner.Kind,
				Group: ownerGV.Group,
			}
			log.Info("Watching child resource", "kind", resource.GroupVersionKind(),
				"enqueue_annotation_type", ownerGK.String())
			err = contents.Controller.Watch(source.Kind(cache, client.Object(resource), &handler.LoggingEnqueueRequestForAnnotation{
				EnqueueRequestForAnnotation: libhandler.EnqueueRequestForAnnotation[client.Object]{Type: ownerGK},
			}, predicate.DependentPredicate{}))
			if err != nil {
				log.Error(err, "Failed to watch child resource",
					"kind", resource.GroupVersionKind(), "enqueue_kind", u.GroupVersionKind())
				return err
			}
		}
	} else {
		log.Info("Resource will not be watched/cached.", "GVK", resource.GroupVersionKind())
	}
	return nil
}

func removeAuthorizationHeader(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		req.Header.Del("Authorization")
		h.ServeHTTP(w, req)
	})
}

// Helper function used by recovering dependent watches and owner ref injection.
func getRequestOwnerRef(req *http.Request) (*kubeconfig.NamespacedOwnerReference, error) {
	owner := kubeconfig.NamespacedOwnerReference{}
	user, _, ok := req.BasicAuth()
	if !ok {
		return nil, nil
	}
	authString, err := base64.StdEncoding.DecodeString(user)
	if err != nil {
		m := "Could not base64 decode username"
		log.Error(err, m)
		return &owner, err
	}
	// Set owner to NamespacedOwnerReference, which has metav1.OwnerReference
	// as a subset along with the Namespace of the owner. Please see the
	// kubeconfig.NamespacedOwnerReference type for more information. The
	// namespace is required when creating the reconcile requests.
	if err := json.Unmarshal(authString, &owner); err != nil {
		m := "Could not unmarshal auth string"
		log.Error(err, m)
		return &owner, err
	}
	return &owner, err
}

func getGVKFromRequestInfo(r *k8sRequest.RequestInfo, restMapper meta.RESTMapper) (schema.GroupVersionKind, error) {
	gvr := schema.GroupVersionResource{
		Group:    r.APIGroup,
		Version:  r.APIVersion,
		Resource: r.Resource,
	}
	return restMapper.KindFor(gvr)
}

type apiResources struct {
	mu               *sync.RWMutex
	gvkToAPIResource map[string]metav1.APIResource
	discoveryClient  discovery.DiscoveryInterface
}

func (a *apiResources) resetResources() error {
	a.mu.Lock()
	defer a.mu.Unlock()

	_, apisResourceList, err := a.discoveryClient.ServerGroupsAndResources()
	if err != nil {
		return err
	}

	a.gvkToAPIResource = map[string]metav1.APIResource{}

	for _, apiResource := range apisResourceList {
		gv, err := schema.ParseGroupVersion(apiResource.GroupVersion)
		if err != nil {
			return err
		}
		for _, resource := range apiResource.APIResources {
			// Names containing a "/" are subresources and should be ignored
			if strings.Contains(resource.Name, "/") {
				continue
			}
			gvk := schema.GroupVersionKind{
				Group:   gv.Group,
				Version: gv.Version,
				Kind:    resource.Kind,
			}

			a.gvkToAPIResource[gvk.String()] = resource
		}
	}

	return nil
}

func (a *apiResources) IsVirtualResource(gvk schema.GroupVersionKind) (bool, error) {
	a.mu.RLock()
	apiResource, ok := a.gvkToAPIResource[gvk.String()]
	a.mu.RUnlock()

	if !ok {
		//reset the resources
		err := a.resetResources()
		if err != nil {
			return false, err
		}
		// retry to get the resource
		a.mu.RLock()
		apiResource, ok = a.gvkToAPIResource[gvk.String()]
		a.mu.RUnlock()
		if !ok {
			return false, fmt.Errorf("unable to get api resource for gvk: %v", gvk)
		}
	}

	allVerbs := discovery.SupportsAllVerbs{
		Verbs: []string{"watch", "get", "list"},
	}

	if !allVerbs.Match(gvk.GroupVersion().String(), &apiResource) {
		return true, nil
	}

	return false, nil
}
