#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <iostream>
#include <fstream>
#include <sstream>
#include <vector>
#include <string>
#include <cmath>
#include <algorithm>
#include <random>
#include <limits>
#include <numeric>
#include <chrono>

namespace py = pybind11;

// --- DATA STRUCTURES ---

struct Point {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
    int type = 1; // 0: Travel (G00), 1: Cutting (G01)
};

struct Contour {
    std::vector<Point> points;
    int regionId = -1;
    bool isMicroPad = false;
    double area = 0.0;
    Point centroid{0.0, 0.0, 0.0, 0};

    Point startPoint(bool flipped = false) const { 
        return flipped ? points.back() : points.front(); 
    }
    Point endPoint(bool flipped = false) const { 
        return flipped ? points.front() : points.back(); 
    }
};

struct Gene {
    int contourIdx;
    bool isFlipped = false;
};

struct OptimizationReport {
    double originalDistance = 0.0;
    double optimizedDistance = 0.0;
    double timeTakenMs = 0.0;
    int contourCount = 0;
};

// --- CONFIGURATION STRUCTS ---

struct Opt2Config {
    int maxIterations = 1000;
};

struct SAConfig {
    double initialTemp = 1000.0;
    double coolingRate = 0.995;
    double minTemp = 0.001;
};

struct GAConfig {
    int popSize = 50;
    int generations = 200;
    double mutationRate = 0.15;
    
    // Configs khusus Algoritma 5 (PCB-Aware)
    bool enableThermalPenalty = true;
    int regionStrategy = 0; // 0: Disabled, 1: Smallest First, 2: Largest First, 3: Center-Out
    double thermalRadius = 2.0; // mm
    double maxFeedrateG0 = 3000.0; // mm/min
    double acceleration = 500.0; // mm/s^2
};

// --- MAIN OPTIMIZER ENGINE CLASS ---

class GCodeOptimizer {
private:
    std::vector<Point> rawPoints;
    std::vector<Point> optimizedPoints;
    std::vector<Contour> contours;
    Point startPosition{0.0, 0.0, 0.0, 0};
    Point globalCentroid{0.0, 0.0, 0.0, 0};

    Opt2Config opt2Config;
    SAConfig saConfig;
    GAConfig gaConfig;

    bool safeStod(const std::string& str, double& result) {
        if (str.empty()) return false;
        try {
            size_t idx;
            result = std::stod(str, &idx);
            return true;
        } catch (...) { return false; }
    }

    double euclideanDistance(const Point& a, const Point& b) {
        return std::hypot(a.x - b.x, a.y - b.y);
    }

    // Kinematika realistis memperhitungkan Akselerasi GRBL Sculpfun
    double calculateKinematicTime(double distance) {
        if (distance <= 0.0001) return 0.0;
        double vMax = gaConfig.maxFeedrateG0 / 60.0; // mm/s
        double a = gaConfig.acceleration; // mm/s^2
        
        double dAccel = (vMax * vMax) / a;
        if (distance < dAccel) {
            return 2.0 * std::sqrt(distance / a);
        } else {
            return (vMax / a) + ((distance - dAccel) / vMax);
        }
    }

    void extractAndAnalyzeContours() {
        contours.clear();
        Contour currentContour;

        for (size_t i = 0; i < rawPoints.size(); ++i) {
            if (rawPoints[i].type == 1) { // G01 Cutting
                if (currentContour.points.empty() && i > 0) {
                    currentContour.points.push_back(rawPoints[i - 1]);
                }
                currentContour.points.push_back(rawPoints[i]);
            } else { // G00 Travel
                if (!currentContour.points.empty()) {
                    contours.push_back(currentContour);
                    currentContour.points.clear();
                }
            }
        }
        if (!currentContour.points.empty()) {
            contours.push_back(currentContour);
        }

        if (contours.empty()) return;

        // Analisa Geometri & Spatial Clustering (Centroid & Bounding Box)
        double sumX = 0.0, sumY = 0.0;
        int totalPts = 0;

        for (auto& cnt : contours) {
            double minX = std::numeric_limits<double>::max(), maxX = std::numeric_limits<double>::lowest();
            double minY = std::numeric_limits<double>::max(), maxY = std::numeric_limits<double>::lowest();
            double cX = 0.0, cY = 0.0;

            for (const auto& pt : cnt.points) {
                minX = std::min(minX, pt.x); maxX = std::max(maxX, pt.x);
                minY = std::min(minY, pt.y); maxY = std::max(maxY, pt.y);
                cX += pt.x; cY += pt.y;
                sumX += pt.x; sumY += pt.y;
                totalPts++;
            }

            double w = maxX - minX;
            double h = maxY - minY;
            cnt.area = w * h;
            cnt.centroid = {cX / cnt.points.size(), cY / cnt.points.size(), 0.0, 0};
            
            // Deteksi Micro-Pad (QFP) berdasarkan bounding box
            if (std::hypot(w, h) < 3.0) {
                cnt.isMicroPad = true;
            }
        }

        globalCentroid = {sumX / totalPts, sumY / totalPts, 0.0, 0};

        // Clustering Region berbasis Jarak Centroid (< 3.0 mm)
        int currentRegionId = 0;
        for (size_t i = 0; i < contours.size(); ++i) {
            if (contours[i].regionId != -1) continue;
            contours[i].regionId = currentRegionId;

            for (size_t j = i + 1; j < contours.size(); ++j) {
                if (contours[j].regionId == -1 && 
                    euclideanDistance(contours[i].centroid, contours[j].centroid) < 3.0) {
                    contours[j].regionId = currentRegionId;
                }
            }
            currentRegionId++;
        }
    }

    std::vector<Point> rebuildPathFromGenes(const std::vector<Gene>& genes) {
        std::vector<Point> path;
        Point currentPos = startPosition;

        for (const auto& g : genes) {
            const auto& cnt = contours[g.contourIdx];
            Point travelTarget = cnt.startPoint(g.isFlipped);
            travelTarget.type = 0; // Rapid travel G00
            path.push_back(travelTarget);

            if (!g.isFlipped) {
                for (const auto& pt : cnt.points) path.push_back(pt);
            } else {
                for (auto it = cnt.points.rbegin(); it != cnt.points.rend(); ++it) path.push_back(*it);
            }
            currentPos = cnt.endPoint(g.isFlipped);
        }
        return path;
    }

    double calculateTotalTravelDistance(const std::vector<Contour>& t) {
        double dist = 0.0;
        Point pos = startPosition;
        for (const auto& cnt : t) {
            dist += euclideanDistance(pos, cnt.startPoint());
            pos = cnt.endPoint();
        }
        return dist;
    }

    // --- ALGORITHMS 1 - 3 (STANDARD TSP) ---
    std::vector<Contour> solveNearestNeighbor() {
        std::vector<Contour> result;
        std::vector<bool> visited(contours.size(), false);
        Point currentPos = startPosition;

        for (size_t i = 0; i < contours.size(); ++i) {
            int bestIdx = -1;
            double minDistance = std::numeric_limits<double>::max();

            for (size_t j = 0; j < contours.size(); ++j) {
                if (!visited[j]) {
                    double dist = euclideanDistance(currentPos, contours[j].startPoint());
                    if (dist < minDistance) {
                        minDistance = dist;
                        bestIdx = static_cast<int>(j);
                    }
                }
            }
            if (bestIdx != -1) {
                visited[bestIdx] = true;
                result.push_back(contours[bestIdx]);
                currentPos = contours[bestIdx].endPoint();
            }
        }
        return result;
    }

    std::vector<Contour> solve2Opt() {
        std::vector<Contour> tour = solveNearestNeighbor();
        if (tour.size() <= 2) return tour;

        bool improved = true;
        double bestDistance = calculateTotalTravelDistance(tour);
        int iterCount = 0;

        while (improved && iterCount < opt2Config.maxIterations) {
            improved = false;
            iterCount++;
            for (size_t i = 0; i < tour.size() - 1; ++i) {
                for (size_t j = i + 1; j < tour.size(); ++j) {
                    std::vector<Contour> newTour = tour;
                    std::reverse(newTour.begin() + i, newTour.begin() + j + 1);
                    double newDistance = calculateTotalTravelDistance(newTour);
                    if (newDistance < bestDistance) {
                        bestDistance = newDistance;
                        tour = newTour;
                        improved = true;
                    }
                }
            }
        }
        return tour;
    }

    std::vector<Contour> solveSimulatedAnnealing() {
        std::vector<Contour> currentTour = solveNearestNeighbor();
        if (currentTour.size() <= 2) return currentTour;

        std::vector<Contour> bestTour = currentTour;
        double currentCost = calculateTotalTravelDistance(currentTour);
        double bestCost = currentCost;

        double temp = saConfig.initialTemp;
        double coolingRate = saConfig.coolingRate;
        double minTemp = saConfig.minTemp;

        std::default_random_engine generator(1337);

        while (temp > minTemp) {
            std::uniform_int_distribution<int> dist(0, currentTour.size() - 1);
            int idx1 = dist(generator);
            int idx2 = dist(generator);

            std::vector<Contour> newTour = currentTour;
            std::swap(newTour[idx1], newTour[idx2]);

            double newCost = calculateTotalTravelDistance(newTour);
            double delta = newCost - currentCost;

            if (delta < 0 || std::exp(-delta / temp) > ((double)rand() / RAND_MAX)) {
                currentTour = newTour;
                currentCost = newCost;
                if (currentCost < bestCost) {
                    bestTour = currentTour;
                    bestCost = currentCost;
                }
            }
            temp *= coolingRate;
        }
        return bestTour;
    }

    // --- ALGORITHM 4: STANDARD GENERAL GA ---
    std::vector<Contour> solveGeneticAlgorithm() {
        if (contours.size() <= 2) return contours;

        const int popSize = gaConfig.popSize;
        const int generations = gaConfig.generations;
        const double mutationRate = gaConfig.mutationRate;
        const size_t numContours = contours.size();

        std::default_random_engine rng(42);
        using Individual = std::vector<int>;
        std::vector<Individual> population(popSize);

        Individual baseInd(numContours);
        std::iota(baseInd.begin(), baseInd.end(), 0);

        for (int i = 0; i < popSize; ++i) {
            population[i] = baseInd;
            if (i > 0) std::shuffle(population[i].begin(), population[i].end(), rng);
        }

        auto evalFitness = [&](const Individual& ind) {
            std::vector<Contour> tempTour;
            tempTour.reserve(numContours);
            for (int idx : ind) tempTour.push_back(contours[idx]);
            return calculateTotalTravelDistance(tempTour);
        };

        Individual bestIndividual = population[0];
        double bestCost = evalFitness(bestIndividual);

        for (int gen = 0; gen < generations; ++gen) {
            std::vector<double> costs(popSize);
            for (int i = 0; i < popSize; ++i) {
                costs[i] = evalFitness(population[i]);
                if (costs[i] < bestCost) {
                    bestCost = costs[i];
                    bestIndividual = population[i];
                }
            }

            std::vector<Individual> newPopulation;
            newPopulation.reserve(popSize);
            newPopulation.push_back(bestIndividual);

            std::uniform_int_distribution<int> popDist(0, popSize - 1);
            auto selectParent = [&]() {
                int i1 = popDist(rng);
                int i2 = popDist(rng);
                return (costs[i1] < costs[i2]) ? population[i1] : population[i2];
            };

            while (newPopulation.size() < static_cast<size_t>(popSize)) {
                Individual p1 = selectParent();
                Individual p2 = selectParent();

                std::uniform_int_distribution<int> cutDist(0, numContours - 1);
                int c1 = cutDist(rng);
                int c2 = cutDist(rng);
                if (c1 > c2) std::swap(c1, c2);

                Individual child(numContours, -1);
                std::vector<bool> inChild(numContours, false);

                for (int i = c1; i <= c2; ++i) {
                    child[i] = p1[i];
                    inChild[p1[i]] = true;
                }

                int childIdx = (c2 + 1) % numContours;
                for (size_t i = 0; i < numContours; ++i) {
                    int p2Idx = (c2 + 1 + i) % numContours;
                    int val = p2[p2Idx];
                    if (!inChild[val]) {
                        child[childIdx] = val;
                        childIdx = (childIdx + 1) % numContours;
                    }
                }

                std::uniform_real_distribution<double> probDist(0.0, 1.0);
                if (probDist(rng) < mutationRate) {
                    int m1 = cutDist(rng);
                    int m2 = cutDist(rng);
                    std::swap(child[m1], child[m2]);
                }
                newPopulation.push_back(child);
            }
            population = newPopulation;
        }

        std::vector<Contour> result;
        result.reserve(numContours);
        for (int idx : bestIndividual) result.push_back(contours[idx]);
        return result;
    }

    // --- ALGORITHM 5: DOMAIN-SPECIFIC PCB-AWARE GA ---
    std::vector<Point> solvePcbAwareGA() {
        if (contours.size() <= 2) return rawPoints;

        const int popSize = gaConfig.popSize;
        const int generations = gaConfig.generations;
        const double mutationRate = gaConfig.mutationRate;
        const size_t numContours = contours.size();

        std::default_random_engine rng(1337);
        using Individual = std::vector<Gene>;
        std::vector<Individual> population(popSize);

        Individual baseInd(numContours);
        for (size_t i = 0; i < numContours; ++i) {
            baseInd[i] = {static_cast<int>(i), false};
        }

        for (int i = 0; i < popSize; ++i) {
            population[i] = baseInd;
            if (i > 0) std::shuffle(population[i].begin(), population[i].end(), rng);
        }

        // PCB-Aware Fitness Evaluator
        auto evalFitness = [&](const Individual& ind) {
            double totalCost = 0.0;
            Point currentPos = startPosition;

            for (size_t i = 0; i < ind.size(); ++i) {
                const auto& geneCurr = ind[i];
                const auto& cntCurr = contours[geneCurr.contourIdx];

                // 1. Kinematic G0 Travel Cost
                double dist = euclideanDistance(currentPos, cntCurr.startPoint(geneCurr.isFlipped));
                totalCost += calculateKinematicTime(dist) * 100.0; // Scaled time cost

                // 2. Thermal Penalty (QFP Spacing)
                if (gaConfig.enableThermalPenalty && i > 0) {
                    const auto& genePrev = ind[i - 1];
                    const auto& cntPrev = contours[genePrev.contourIdx];

                    if (cntCurr.isMicroPad && cntPrev.isMicroPad) {
                        double centerDist = euclideanDistance(cntCurr.centroid, cntPrev.centroid);
                        if (centerDist < gaConfig.thermalRadius) {
                            totalCost += 500.0 * (1.0 - (centerDist / gaConfig.thermalRadius));
                        }
                    }
                }

                // 3. Region Strategy Penalty
                if (gaConfig.regionStrategy != 0 && i > 0) {
                    const auto& genePrev = ind[i - 1];
                    const auto& cntPrev = contours[genePrev.contourIdx];

                    if (gaConfig.regionStrategy == 1) { // Smallest First
                        if (cntCurr.area < cntPrev.area && cntPrev.regionId != cntCurr.regionId) {
                            totalCost += 300.0;
                        }
                    } else if (gaConfig.regionStrategy == 2) { // Largest First
                        if (cntCurr.area > cntPrev.area && cntPrev.regionId != cntCurr.regionId) {
                            totalCost += 300.0;
                        }
                    } else if (gaConfig.regionStrategy == 3) { // Center-Out (Centroid)
                        double distCurrCenter = euclideanDistance(cntCurr.centroid, globalCentroid);
                        double distPrevCenter = euclideanDistance(cntPrev.centroid, globalCentroid);
                        if (distCurrCenter < distPrevCenter && cntPrev.regionId != cntCurr.regionId) {
                            totalCost += 300.0;
                        }
                    }
                }

                currentPos = cntCurr.endPoint(geneCurr.isFlipped);
            }
            return totalCost;
        };

        Individual bestIndividual = population[0];
        double bestCost = evalFitness(bestIndividual);

        for (int gen = 0; gen < generations; ++gen) {
            std::vector<double> costs(popSize);
            for (int i = 0; i < popSize; ++i) {
                costs[i] = evalFitness(population[i]);
                if (costs[i] < bestCost) {
                    bestCost = costs[i];
                    bestIndividual = population[i];
                }
            }

            std::vector<Individual> newPopulation;
            newPopulation.reserve(popSize);
            newPopulation.push_back(bestIndividual);

            std::uniform_int_distribution<int> popDist(0, popSize - 1);
            auto selectParent = [&]() {
                int i1 = popDist(rng); int i2 = popDist(rng);
                return (costs[i1] < costs[i2]) ? population[i1] : population[i2];
            };

            while (newPopulation.size() < static_cast<size_t>(popSize)) {
                Individual p1 = selectParent();
                Individual p2 = selectParent();

                std::uniform_int_distribution<int> cutDist(0, numContours - 1);
                int c1 = cutDist(rng); int c2 = cutDist(rng);
                if (c1 > c2) std::swap(c1, c2);

                Individual child(numContours);
                std::vector<bool> inChild(numContours, false);

                for (int i = c1; i <= c2; ++i) {
                    child[i] = p1[i];
                    inChild[p1[i].contourIdx] = true;
                }

                int childIdx = (c2 + 1) % numContours;
                for (size_t i = 0; i < numContours; ++i) {
                    int p2Idx = (c2 + 1 + i) % numContours;
                    const auto& geneP2 = p2[p2Idx];
                    if (!inChild[geneP2.contourIdx]) {
                        child[childIdx] = geneP2;
                        childIdx = (childIdx + 1) % numContours;
                    }
                }

                // Dual-Mode Mutation (Swap or Flip)
                std::uniform_real_distribution<double> probDist(0.0, 1.0);
                if (probDist(rng) < mutationRate) {
                    int m1 = cutDist(rng);
                    int m2 = cutDist(rng);
                    if (probDist(rng) < 0.5) {
                        std::swap(child[m1], child[m2]); // Swap Order
                    } else {
                        child[m1].isFlipped = !child[m1].isFlipped; // Flip Orientation
                    }
                }
                newPopulation.push_back(child);
            }
            population = newPopulation;
        }

        return rebuildPathFromGenes(bestIndividual);
    }

public:
    GCodeOptimizer() {}

    void set2OptConfig(int maxIter) { opt2Config.maxIterations = maxIter; }
    void setSAConfig(double initialTemp, double coolingRate, double minTemp) {
        saConfig.initialTemp = initialTemp;
        saConfig.coolingRate = coolingRate;
        saConfig.minTemp = minTemp;
    }
    void setGAConfig(int popSize, int generations, double mutationRate, 
                     bool enableThermal, int regionStrat, double thermalRad, 
                     double maxG0, double accel) {
        gaConfig.popSize = popSize;
        gaConfig.generations = generations;
        gaConfig.mutationRate = mutationRate;
        gaConfig.enableThermalPenalty = enableThermal;
        gaConfig.regionStrategy = regionStrat;
        gaConfig.thermalRadius = thermalRad;
        gaConfig.maxFeedrateG0 = maxG0;
        gaConfig.acceleration = accel;
    }

    void loadGCode(const std::string& filepath) {
        rawPoints.clear();
        std::ifstream file(filepath);
        if (!file.is_open()) return;

        std::string line;
        double curX = 0.0, curY = 0.0, curZ = 0.0;
        std::string currentModal = "G01";

        while (std::getline(file, line)) {
            size_t commentPos = line.find('(');
            if (commentPos != std::string::npos) line = line.substr(0, commentPos);
            commentPos = line.find(';');
            if (commentPos != std::string::npos) line = line.substr(0, commentPos);
            commentPos = line.find('[');
            if (commentPos != std::string::npos) line = line.substr(0, commentPos);

            if (line.empty() || line[0] == '%') continue;

            std::stringstream ss(line);
            std::string token;
            double targetX = curX, targetY = curY, targetZ = curZ;
            bool hasX = false, hasY = false, hasZ = false;
            std::string command = "";

            while (ss >> token) {
                if (token.length() < 2) continue;
                char prefix = std::toupper(token[0]);
                std::string valStr = token.substr(1);

                if (prefix == 'G') {
                    double gVal;
                    if (safeStod(valStr, gVal)) {
                        int gNum = static_cast<int>(gVal);
                        if (gNum == 0) command = "G00";
                        else if (gNum == 1) command = "G01";
                    }
                } 
                else if (prefix == 'X') { hasX = safeStod(valStr, targetX); }
                else if (prefix == 'Y') { hasY = safeStod(valStr, targetY); }
                else if (prefix == 'Z') { hasZ = safeStod(valStr, targetZ); }
            }

            if (command.empty() && (hasX || hasY || hasZ)) command = currentModal;
            else if (!command.empty()) currentModal = command;

            if (hasX || hasY || hasZ) {
                int type = (command == "G00") ? 0 : 1;
                rawPoints.push_back({targetX, targetY, targetZ, type});
                curX = targetX; curY = targetY; curZ = targetZ;
            }
        }
        file.close();
        extractAndAnalyzeContours();
        optimizedPoints = rawPoints;
    }

    std::vector<Point> getRawPoints() { return rawPoints; }

    std::vector<Point> optimizePath(int method_type) {
        if (contours.empty()) return rawPoints;

        if (method_type == 4) {
            optimizedPoints = solvePcbAwareGA();
            return optimizedPoints;
        }

        std::vector<Contour> orderedContours;
        if (method_type == 0) orderedContours = solveNearestNeighbor();
        else if (method_type == 1) orderedContours = solve2Opt();
        else if (method_type == 2) orderedContours = solveSimulatedAnnealing();
        else if (method_type == 3) orderedContours = solveGeneticAlgorithm();
        else return rawPoints;

        std::vector<Gene> genes;
        for (size_t i = 0; i < orderedContours.size(); ++i) {
            int origIdx = 0;
            for (size_t j = 0; j < contours.size(); ++j) {
                if (&contours[j] == &orderedContours[i]) { origIdx = j; break; }
            }
            genes.push_back({origIdx, false});
        }

        optimizedPoints = rebuildPathFromGenes(genes);
        return optimizedPoints;
    }

    OptimizationReport runWithReport(int method_type) {
        OptimizationReport report;
        report.contourCount = static_cast<int>(contours.size());
        report.originalDistance = calculateTotalTravelDistance(contours);

        auto start = std::chrono::high_resolution_clock::now();
        optimizePath(method_type);
        auto end = std::chrono::high_resolution_clock::now();

        std::chrono::duration<double, std::milli> duration = end - start;
        report.timeTakenMs = duration.count();

        double finalDist = 0.0;
        Point pos = startPosition;
        for (const auto& pt : optimizedPoints) {
            if (pt.type == 0) finalDist += euclideanDistance(pos, pt);
            pos = pt;
        }
        report.optimizedDistance = finalDist;
        return report;
    }
};

// --- PYBIND11 MODULE BINDINGS ---

PYBIND11_MODULE(gcode_engine, m) {
    py::class_<Point>(m, "Point")
        .def_readwrite("x", &Point::x)
        .def_readwrite("y", &Point::y)
        .def_readwrite("z", &Point::z)
        .def_readwrite("type", &Point::type);

    py::class_<OptimizationReport>(m, "OptimizationReport")
        .def_readwrite("originalDistance", &OptimizationReport::originalDistance)
        .def_readwrite("optimizedDistance", &OptimizationReport::optimizedDistance)
        .def_readwrite("timeTakenMs", &OptimizationReport::timeTakenMs)
        .def_readwrite("contourCount", &OptimizationReport::contourCount);

    py::class_<GCodeOptimizer>(m, "GCodeOptimizer")
        .def(py::init<>())
        .def("loadGCode", &GCodeOptimizer::loadGCode)
        .def("getRawPoints", &GCodeOptimizer::getRawPoints)
        .def("optimizePath", &GCodeOptimizer::optimizePath)
        .def("runWithReport", &GCodeOptimizer::runWithReport)
        .def("set2OptConfig", &GCodeOptimizer::set2OptConfig)
        .def("setSAConfig", &GCodeOptimizer::setSAConfig)
        .def("setGAConfig", &GCodeOptimizer::setGAConfig);
}