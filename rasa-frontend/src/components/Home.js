// src/components/Home.js
import React from 'react';
import { Link } from 'react-router-dom';       // ← add this
import './Home.css';
import Apache_Jena from './imgs/Apache_Jena.jpg'; // Import the image at the top
import nlinegiftoolsgif from './imgs/thingsboard.jpg'; // Import the image at the top
import pg2png from './imgs/pg-2.jpg'; // Import the image at the top
import jupyter3 from './imgs/jupyter-3.jpg'; // Import the image at the top
import menuimage from './imgs/menu_image.jpg'; // Import the image at the top
import bldgpng from './imgs/bldg.jpg'; // Import the image at the top
import APIgif from './imgs/api.jpg'; // Import the image at the top
import GraphDB from './imgs/GraphDB.jpg'; // Import the image at the top



export default function Home() {
  const openService = url => window.open(url, '_blank');

 const services = [
    { img: Apache_Jena, title: "Jena Fuseki Server", text: "Semantic Web Framework", url: "http://localhost:3030",width:  "70%", height: "150px" },
    { img: nlinegiftoolsgif, title: "ThingsBoard Server", text: "IoT Platform", url: "http://localhost:8080",width:  "70%", height: "150px" },
    { img: pg2png, title: "PgAdmin Server", text: "Database Management", url: "http://localhost:5050" ,width:  "70%", height: "150px"},
    { img: jupyter3, title: "Jupyter Notebook", text: "Notebooks for data analysis", url: "http://localhost:8888",width:  "70%", height: "150px" },
    { img: menuimage, title: "Adminer Service", text: "Database Management", url: "http://localhost:8282" ,width:  "70%", height: "150px"},
    { img: bldgpng, title: "3D-Abacws Service", text: "3D Visualization", url: "http://localhost:8090" ,width:  "70%", height: "150px"},
    { img: APIgif, title: "3D-API", text: "API for 3D Services", url: "http://localhost:8091" ,width:  "70%", height: "150px"},
    { img: GraphDB, title: "GraphDB", text: "Graph DBMS for SPARQL", url: "http://localhost:7200" ,width:  "70%", height: "150px"},
  ];

  return (
    <div className="home-body">

      {/* 🌊 Wave layers */}
      <div className="wave"></div>
      <div className="wave"></div>
      <div className="wave"></div>
      {/* Navbar */}
      <nav className="navbar navbar-expand-lg navbar-light bg-light">
        <div className="container">
          {/* Brand → goes to your home route */}
          <Link className="navbar-brand" to="/">Abacws SmartBot</Link>

          <button
            className="navbar-toggler"
            type="button"
            data-toggle="collapse"
            data-target="#navbarScroll"
            aria-controls="navbarScroll"
            aria-expanded="false"
            aria-label="Toggle navigation"
          >
            <span className="navbar-toggler-icon" />
          </button>

          <div className="collapse navbar-collapse" id="navbarScroll">
            <ul className="navbar-nav mr-auto my-2 my-lg-0 navbar-nav-scroll">
              <li className="nav-item">
                {/* Home link */}
                <Link className="nav-link active" to="/">Home</Link>
              </li>
              <li className="nav-item">
                {/* Docs route (create a /docs page or adjust as needed) */}
                <Link className="nav-link" to="/docs">Docs</Link>
              </li>
              <li className="nav-item dropdown">
                {/* Dropdown parent – could point to a page of links */}
                <Link
                  className="nav-link dropdown-toggle"
                  to="/links"
                  role="button"
                  data-toggle="dropdown"
                  aria-expanded="false"
                >
                  Links
                </Link>
                <ul className="dropdown-menu">
                  <li>
                    <Link className="dropdown-item" to="/action/3.1">
                      Action
                    </Link>
                  </li>
                  <li>
                    <Link className="dropdown-item" to="/action/3.2">
                      Another action
                    </Link>
                  </li>
                  <li><hr className="dropdown-divider" /></li>
                  <li>
                    <Link className="dropdown-item" to="/action/3.3">
                      Something else here
                    </Link>
                  </li>
                </ul>
              </li>
              <li className="nav-item">
                {/* If you don’t have an About page yet, either create one or hide this */}
                <Link className="nav-link disabled" to="/" aria-disabled="true">
                  About us
                </Link>
              </li>
            </ul>

            <form className="form-inline my-2 my-lg-0">
              <input
                className="form-control mr-sm-2"
                type="search"
                placeholder="Search"
                aria-label="Search"
              />
              <button className="btn btn-outline-success my-2 my-sm-0" type="submit">
                Search
              </button>
            </form>
          </div>
        </div>
      </nav>

      {/* Intro */}
      <div className="container mt-4" id="content">
        <h1>Abacws SmartBot – Your Virtual Assistant</h1>
        <p>
          Click on the chat button to start a conversation or select a service below:
        </p>
      </div>

      {/* Services grid */}
      <div className="service-container container" id="content">
        <div className="row row-cols-1 row-cols-md-2 row-cols-lg-4 g-4">
          {services.map((svc, i) => (
            <div className="col" key={i}>
              <div className="card-transparent service-card">
                <img
                  src={svc.img}
                  className="card-img-top"
                  alt={svc.title}
                    // apply your custom dimensions here:
                    style={{
                      width: svc.width,
                      height: svc.height,
                      objectFit: 'cover',
                      marginBottom: '10px'
                    }}
                />
                <div className="card-body">
                  <h5 className="card-title">{svc.title}</h5>
                  <p className="card-text">{svc.text}</p>
                  <div className="card-footer">
                    <button
                      className="btn btn-primary"
                      onClick={() => openService(svc.url)}
                    >
                      Open Service
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
