function getStateValue(state, path) {
    return String(path || '')
        .split('.')
        .filter(Boolean)
        .reduce((cursor, key) => (cursor && key in cursor ? cursor[key] : undefined), state);
}

function matchesSelectorPart(node, part) {
    if (!node || !part) {
        return false;
    }
    if (part.startsWith('.')) {
        return String(node.className || '')
            .split(/\s+/)
            .filter(Boolean)
            .includes(part.slice(1));
    }
    if (part.startsWith('#')) {
        return node.id === part.slice(1);
    }
    return String(node.tagName || '').toLowerCase() === part.toLowerCase();
}

function findFirstMatch(root, parts, index = 0) {
    for (const child of root.children) {
        if (matchesSelectorPart(child, parts[index])) {
            if (index === parts.length - 1) {
                return child;
            }
            const nested = findFirstMatch(child, parts, index + 1);
            if (nested) {
                return nested;
            }
        }
        const descendant = findFirstMatch(child, parts, index);
        if (descendant) {
            return descendant;
        }
    }
    return null;
}

function findAllMatches(root, parts, index = 0, results = []) {
    for (const child of root.children) {
        if (matchesSelectorPart(child, parts[index])) {
            if (index === parts.length - 1) {
                results.push(child);
            } else {
                findAllMatches(child, parts, index + 1, results);
            }
        }
        findAllMatches(child, parts, index, results);
    }
    return results;
}

class FakeNode {
    constructor(tagName, ownerDocument, nodeType = 'element') {
        this.tagName = String(tagName || '').toUpperCase();
        this.ownerDocument = ownerDocument;
        this.nodeType = nodeType;
        this.children = [];
        this.parentNode = null;
        this.attributes = {};
        this.dataset = {};
        this.style = {};
        this.className = '';
        this.id = '';
        this.hidden = false;
        this.disabled = false;
        this._value = '';
        this._checked = false;
        this._textContent = '';
        this._listeners = new Map();
        this.classList = {
            add: (...tokens) => {
                const set = new Set(String(this.className || '').split(/\s+/).filter(Boolean));
                tokens.flat().filter(Boolean).forEach((token) => set.add(token));
                this.className = [...set].join(' ');
            },
            remove: (...tokens) => {
                const removeSet = new Set(tokens.flat().filter(Boolean));
                this.className = String(this.className || '')
                    .split(/\s+/)
                    .filter((token) => token && !removeSet.has(token))
                    .join(' ');
            },
            contains: (token) => String(this.className || '')
                .split(/\s+/)
                .filter(Boolean)
                .includes(token),
            toggle: (token, force) => {
                const hasToken = this.classList.contains(token);
                const shouldAdd = force === undefined ? !hasToken : !!force;
                if (shouldAdd) {
                    this.classList.add(token);
                    return true;
                }
                this.classList.remove(token);
                return false;
            },
        };
    }

    set value(nextValue) {
        this._value = String(nextValue ?? '');
    }

    get value() {
        return this._value;
    }

    set checked(nextValue) {
        this._checked = !!nextValue;
    }

    get checked() {
        return this._checked;
    }

    set textContent(value) {
        this._textContent = String(value ?? '');
        this.children = [];
    }

    get textContent() {
        return `${this._textContent}${this.children.map((child) => child.textContent).join('')}`;
    }

    appendChild(child) {
        if (!child) {
            return child;
        }
        if (child.nodeType === 'fragment') {
            for (const nested of child.children.slice()) {
                this.appendChild(nested);
            }
            child.children = [];
            return child;
        }
        child.parentNode = this;
        this.children.push(child);
        return child;
    }

    remove() {
        if (!this.parentNode) {
            return;
        }
        this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
        this.parentNode = null;
    }

    replaceWith(node) {
        if (!this.parentNode || !node) {
            return;
        }
        const index = this.parentNode.children.indexOf(this);
        if (index < 0) {
            return;
        }
        node.parentNode = this.parentNode;
        this.parentNode.children.splice(index, 1, node);
        this.parentNode = null;
    }

    setAttribute(name, value) {
        const nextName = String(name || '');
        const nextValue = String(value ?? '');
        this.attributes[nextName] = nextValue;
        if (nextName === 'class') {
            this.className = nextValue;
        }
        if (nextName === 'id') {
            this.id = nextValue;
            this.ownerDocument._registerById(nextValue, this);
        }
    }

    setAttributeNS(_namespace, name, value) {
        this.setAttribute(name, value);
    }

    querySelector(selector) {
        const parts = String(selector || '').trim().split(/\s+/).filter(Boolean);
        if (parts.length === 0) {
            return null;
        }
        return findFirstMatch(this, parts);
    }

    querySelectorAll(selector) {
        const parts = String(selector || '').trim().split(/\s+/).filter(Boolean);
        if (parts.length === 0) {
            return [];
        }
        return findAllMatches(this, parts);
    }

    addEventListener(type, handler) {
        const key = String(type || '');
        if (!this._listeners.has(key)) {
            this._listeners.set(key, []);
        }
        this._listeners.get(key).push(handler);
    }

    click() {
        for (const handler of this._listeners.get('click') || []) {
            handler({ target: this });
        }
    }

    focus() {}
}

class FakeDocument {
    constructor() {
        this._elementsById = new Map();
        this.body = new FakeNode('body', this);
    }

    _registerById(id, element) {
        if (id) {
            this._elementsById.set(id, element);
        }
    }

    createElement(tagName) {
        return new FakeNode(tagName, this);
    }

    createElementNS(_namespace, tagName) {
        return new FakeNode(tagName, this);
    }

    createDocumentFragment() {
        return new FakeNode('#fragment', this, 'fragment');
    }

    getElementById(id) {
        return this._elementsById.get(String(id || '')) || null;
    }
}

export function installDomStub() {
    const previousDocument = globalThis.document;
    const document = new FakeDocument();
    globalThis.document = document;

    return {
        document,
        registerElement(id, element) {
            element.id = id;
            document._registerById(id, element);
            return element;
        },
        createPage(selectors = {}, state = {}) {
            return {
                $(selector) {
                    return selectors[selector] || null;
                },
                getState(path) {
                    return getStateValue(state, path);
                },
            };
        },
        restore() {
            if (previousDocument === undefined) {
                delete globalThis.document;
                return;
            }
            globalThis.document = previousDocument;
        },
    };
}
